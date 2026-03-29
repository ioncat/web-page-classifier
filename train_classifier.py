# =============================================================================
# train_classifier.py — fine-tune xlm-roberta-base на датасете из export_dataset.py
#
# Использование:
#   python train_classifier.py                              обучение с дефолтами
#   python train_classifier.py --dataset train.jsonl        другой датасет
#   python train_classifier.py --epochs 15 --batch-size 16  параметры обучения
#   python train_classifier.py --base-model xlm-roberta-large  другая базовая модель
#   python train_classifier.py --output models/v2           другая папка для модели
#   python train_classifier.py --eval-only                  только оценка (без обучения)
#
# Результат:
#   models/url_classifier/          — HuggingFace модель + токенизатор
#   models/url_classifier/label_map.json  — маппинг label↔id
#   models/url_classifier/metrics.json    — accuracy, macro-F1, per-class F1
#   models/url_classifier/confusion_matrix.png
# =============================================================================

import argparse
import json
import sys
import io
import os
import time
from collections import Counter

import numpy as np
import torch
import torch.nn as nn
from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
)
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    Trainer,
    TrainingArguments,
    EarlyStoppingCallback,
)

if sys.platform == "win32" and hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


# ── Датасет ──────────────────────────────────────────────────────────────────

class ClassificationDataset(torch.utils.data.Dataset):
    def __init__(self, encodings, labels):
        self.encodings = encodings
        self.labels = labels

    def __len__(self):
        return len(self.labels)

    def __getitem__(self, idx):
        item = {k: v[idx] for k, v in self.encodings.items()}
        item["labels"] = self.labels[idx]
        return item


# ── Trainer с class weights ──────────────────────────────────────────────────

class WeightedTrainer(Trainer):
    """Trainer с взвешенным CrossEntropyLoss для несбалансированных классов."""

    def __init__(self, class_weights=None, **kwargs):
        super().__init__(**kwargs)
        if class_weights is not None:
            self.class_weights = class_weights.to(self.args.device)
        else:
            self.class_weights = None

    def compute_loss(self, model, inputs, return_outputs=False, **kwargs):
        labels = inputs.pop("labels")
        outputs = model(**inputs)
        logits = outputs.logits
        if self.class_weights is not None:
            loss_fn = nn.CrossEntropyLoss(weight=self.class_weights)
        else:
            loss_fn = nn.CrossEntropyLoss()
        loss = loss_fn(logits, labels)
        return (loss, outputs) if return_outputs else loss


# ── Загрузка данных ──────────────────────────────────────────────────────────

def load_jsonl(path: str) -> tuple[list[str], list[str]]:
    """Читает JSONL, возвращает (texts, labels)."""
    texts, labels = [], []
    with open(path, encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            texts.append(row["text"])
            labels.append(row["label"])
    return texts, labels


def build_label_map(labels: list[str]) -> tuple[dict[str, int], dict[int, str]]:
    """Создаёт label↔id маппинг (сортировка для воспроизводимости)."""
    unique = sorted(set(labels))
    label2id = {label: i for i, label in enumerate(unique)}
    id2label = {i: label for label, i in label2id.items()}
    return label2id, id2label


def compute_class_weights(labels: list[int], num_classes: int) -> torch.Tensor:
    """Вычисляет веса классов: inverse frequency, нормализованные."""
    counts = Counter(labels)
    total = len(labels)
    weights = torch.zeros(num_classes)
    for cls_id in range(num_classes):
        cnt = counts.get(cls_id, 1)
        weights[cls_id] = total / (num_classes * cnt)
    return weights


# ── Метрики ──────────────────────────────────────────────────────────────────

def compute_metrics(eval_pred):
    logits, labels = eval_pred
    preds = np.argmax(logits, axis=-1)
    acc = accuracy_score(labels, preds)
    f1 = f1_score(labels, preds, average="macro", zero_division=0)
    return {"accuracy": acc, "macro_f1": f1}


# ── Confusion matrix ────────────────────────────────────────────────────────

def save_confusion_matrix(y_true, y_pred, label_names, output_path: str):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import seaborn as sns

    cm = confusion_matrix(y_true, y_pred)
    fig, ax = plt.subplots(figsize=(max(12, len(label_names) * 0.5),
                                     max(10, len(label_names) * 0.4)))
    sns.heatmap(
        cm, annot=True, fmt="d", cmap="Blues",
        xticklabels=label_names, yticklabels=label_names,
        ax=ax, linewidths=0.5,
    )
    ax.set_xlabel("Predicted")
    ax.set_ylabel("True")
    ax.set_title("Confusion Matrix")
    plt.xticks(rotation=45, ha="right", fontsize=7)
    plt.yticks(rotation=0, fontsize=7)
    plt.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    print(f"  Confusion matrix → {output_path}")


# ── Основная функция ────────────────────────────────────────────────────────

def train(
    dataset_path: str = "dataset.jsonl",
    output_dir: str = "models/url_classifier",
    base_model: str = "xlm-roberta-base",
    epochs: int = 10,
    batch_size: int = 32,
    learning_rate: float = 3e-5,
    warmup_ratio: float = 0.1,
    weight_decay: float = 0.01,
    max_length: int = 128,
    test_size: float = 0.15,
    val_size: float = 0.15,
    seed: int = 42,
    eval_only: bool = False,
) -> None:
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Device: {device}")
    if device == "cuda":
        print(f"  GPU: {torch.cuda.get_device_name(0)}")
        vram = torch.cuda.get_device_properties(0).total_memory / 1024**3
        print(f"  VRAM: {vram:.1f} GB")

    # ── Загрузка ──
    print(f"\nДатасет: {dataset_path}")
    texts, labels = load_jsonl(dataset_path)
    print(f"  Записей: {len(texts)}")

    label2id, id2label = build_label_map(labels)
    num_labels = len(label2id)
    print(f"  Категорий: {num_labels}")

    encoded_labels = [label2id[l] for l in labels]

    # ── Split ──
    X_trainval, X_test, y_trainval, y_test = train_test_split(
        texts, encoded_labels,
        test_size=test_size,
        stratify=encoded_labels,
        random_state=seed,
    )
    relative_val = val_size / (1 - test_size)
    X_train, X_val, y_train, y_val = train_test_split(
        X_trainval, y_trainval,
        test_size=relative_val,
        stratify=y_trainval,
        random_state=seed,
    )
    print(f"  Train: {len(X_train)}  Val: {len(X_val)}  Test: {len(X_test)}")

    # ── Class weights ──
    class_weights = compute_class_weights(y_train, num_labels)
    print(f"\n  Class weights (min={class_weights.min():.2f}, max={class_weights.max():.2f}):")
    for i in range(num_labels):
        w = class_weights[i].item()
        if w > 3.0:
            print(f"    {id2label[i]}: {w:.2f}  ← редкий класс")

    # ── Токенизация ──
    print(f"\nТокенизатор: {base_model} (max_length={max_length})")
    tokenizer = AutoTokenizer.from_pretrained(base_model)

    train_enc = tokenizer(X_train, truncation=True, padding=True, max_length=max_length)
    val_enc = tokenizer(X_val, truncation=True, padding=True, max_length=max_length)
    test_enc = tokenizer(X_test, truncation=True, padding=True, max_length=max_length)

    train_dataset = ClassificationDataset(train_enc, y_train)
    val_dataset = ClassificationDataset(val_enc, y_val)
    test_dataset = ClassificationDataset(test_enc, y_test)

    # ── Eval-only: загрузить обученную модель ──
    if eval_only:
        print(f"\n--- Eval-only: загружаем модель из {output_dir} ---")
        model = AutoModelForSequenceClassification.from_pretrained(output_dir)
        model.to(device)
    else:
        # ── Обучение ──
        print(f"\nМодель: {base_model} → {num_labels} классов")
        model = AutoModelForSequenceClassification.from_pretrained(
            base_model,
            num_labels=num_labels,
            id2label=id2label,
            label2id=label2id,
        )

        training_args = TrainingArguments(
            output_dir=output_dir + "/checkpoints",
            num_train_epochs=epochs,
            per_device_train_batch_size=batch_size,
            per_device_eval_batch_size=batch_size * 2,
            learning_rate=learning_rate,
            warmup_ratio=warmup_ratio,
            weight_decay=weight_decay,
            label_smoothing_factor=0.1,
            eval_strategy="epoch",
            save_strategy="no",
            logging_steps=50,
            seed=seed,
            fp16=(device == "cuda"),
            report_to="none",
        )

        trainer = WeightedTrainer(
            class_weights=class_weights,
            model=model,
            args=training_args,
            train_dataset=train_dataset,
            eval_dataset=val_dataset,
            compute_metrics=compute_metrics,
        )

        print(f"\n{'='*60}")
        print(f"Обучение: {epochs} эпох, batch={batch_size}, lr={learning_rate}")
        print(f"  warmup_ratio={warmup_ratio}, weight_decay={weight_decay}")
        print(f"  class_weights=ON, label_smoothing=0.1")
        print(f"{'='*60}\n")

        t0 = time.time()
        trainer.train()
        elapsed = time.time() - t0
        print(f"\nОбучение завершено за {elapsed:.1f} сек ({elapsed/60:.1f} мин)")

        # ── Сохранение ──
        os.makedirs(output_dir, exist_ok=True)
        model.save_pretrained(output_dir)
        tokenizer.save_pretrained(output_dir)

        label_map_path = os.path.join(output_dir, "label_map.json")
        with open(label_map_path, "w", encoding="utf-8") as f:
            json.dump({"label2id": label2id, "id2label": {str(k): v for k, v in id2label.items()}},
                      f, ensure_ascii=False, indent=2)
        print(f"  label_map → {label_map_path}")

    # ── Оценка на test ──
    print(f"\n{'='*60}")
    print("Оценка на тестовом наборе")
    print(f"{'='*60}\n")

    eval_trainer = Trainer(
        model=model,
        args=TrainingArguments(
            output_dir=output_dir + "/eval_tmp",
            per_device_eval_batch_size=batch_size * 2,
            report_to="none",
        ),
        compute_metrics=compute_metrics,
    )

    preds_output = eval_trainer.predict(test_dataset)
    preds = np.argmax(preds_output.predictions, axis=-1)

    acc = accuracy_score(y_test, preds)
    macro_f1 = f1_score(y_test, preds, average="macro", zero_division=0)

    print(f"  Accuracy:  {acc:.4f}")
    print(f"  Macro-F1:  {macro_f1:.4f}")
    target = 0.80
    if macro_f1 >= target:
        print(f"  ✓ Цель достигнута (macro-F1 ≥ {target})")
    else:
        print(f"  ✗ Цель НЕ достигнута (macro-F1 < {target})")

    # ── Per-class report ──
    label_names = [id2label[i] for i in range(num_labels)]
    report = classification_report(
        y_test, preds,
        target_names=label_names,
        zero_division=0,
        output_dict=True,
    )
    print(f"\n{classification_report(y_test, preds, target_names=label_names, zero_division=0)}")

    # ── Сохранение метрик ──
    os.makedirs(output_dir, exist_ok=True)
    metrics = {
        "accuracy": round(acc, 4),
        "macro_f1": round(macro_f1, 4),
        "num_test": len(y_test),
        "num_train": len(y_train),
        "num_val": len(y_val),
        "num_labels": num_labels,
        "base_model": base_model,
        "epochs": epochs,
        "per_class": {
            name: {
                "precision": round(report[name]["precision"], 4),
                "recall": round(report[name]["recall"], 4),
                "f1": round(report[name]["f1-score"], 4),
                "support": report[name]["support"],
            }
            for name in label_names
        },
    }
    metrics_path = os.path.join(output_dir, "metrics.json")
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)
    print(f"  Метрики → {metrics_path}")

    # ── Confusion matrix ──
    cm_path = os.path.join(output_dir, "confusion_matrix.png")
    save_confusion_matrix(y_test, preds, label_names, cm_path)

    # ── Очистка чекпоинтов ──
    import shutil
    for tmp_dir in [output_dir + "/checkpoints", output_dir + "/eval_tmp"]:
        if os.path.isdir(tmp_dir):
            shutil.rmtree(tmp_dir)
            print(f"  Очистка → {tmp_dir}")

    print(f"\n{'='*60}")
    print(f"Модель сохранена → {output_dir}/")
    print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(
        description="Fine-tune классификатор URL на основе xlm-roberta-base",
    )
    parser.add_argument(
        "--dataset", default="dataset.jsonl", metavar="FILE",
        help="путь к JSONL-датасету (по умолчанию: dataset.jsonl)",
    )
    parser.add_argument(
        "--output", default="models/url_classifier", metavar="DIR",
        help="папка для сохранения модели (по умолчанию: models/url_classifier)",
    )
    parser.add_argument(
        "--base-model", default="xlm-roberta-base", metavar="MODEL",
        dest="base_model",
        help="базовая HuggingFace модель (по умолчанию: xlm-roberta-base)",
    )
    parser.add_argument(
        "--epochs", type=int, default=10,
        help="кол-во эпох (по умолчанию: 10)",
    )
    parser.add_argument(
        "--batch-size", type=int, default=32, metavar="N",
        dest="batch_size",
        help="размер батча (по умолчанию: 32)",
    )
    parser.add_argument(
        "--lr", type=float, default=3e-5, dest="learning_rate",
        help="learning rate (по умолчанию: 3e-5)",
    )
    parser.add_argument(
        "--max-length", type=int, default=128, metavar="N",
        dest="max_length",
        help="макс. длина токенов (по умолчанию: 128)",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="random seed (по умолчанию: 42)",
    )
    parser.add_argument(
        "--eval-only", action="store_true", dest="eval_only",
        help="только оценка обученной модели (без обучения)",
    )

    args = parser.parse_args()

    train(
        dataset_path=args.dataset,
        output_dir=args.output,
        base_model=args.base_model,
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        max_length=args.max_length,
        seed=args.seed,
        eval_only=args.eval_only,
    )


if __name__ == "__main__":
    main()
