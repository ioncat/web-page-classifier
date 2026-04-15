/**
 * Animated Graph Background
 * Creates an interactive graph with nodes and connections
 * Positioned as a fixed background behind all content
 */

(function() {
  'use strict';

  class AnimatedGraph {
    constructor() {
      this.canvas = null;
      this.ctx = null;
      this.animationId = null;
      this.nodes = [];
      this.connectionDistance = 200;      /* Увеличена для больше связей */
      this.nodeCount = 100;               /* Больше узлов */
      this.nodeSize = 2.5;                /* Немного больше размер */
      this.lineWidth = 0.8;
      this.lineColor = 'rgba(37, 99, 235, 0.25)';   /* Более видимые линии */
      this.nodeColor = 'rgba(37, 99, 235, 0.6)';    /* Более видимые узлы */
      this.speed = 0.3;                   /* Медленнее для плавности */

      this.init();
    }

    init() {
      // Create canvas
      this.canvas = document.createElement('canvas');
      this.canvas.id = 'animated-graph-canvas';
      this.canvas.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        z-index: 0;
        pointer-events: none;
      `;
      document.body.insertBefore(this.canvas, document.body.firstChild);

      this.ctx = this.canvas.getContext('2d');
      this.resizeCanvas();
      this.createNodes();
      this.animate();

      // Handle window resize
      window.addEventListener('resize', () => this.resizeCanvas());
    }

    resizeCanvas() {
      this.canvas.width = window.innerWidth;
      this.canvas.height = window.innerHeight;
    }

    createNodes() {
      this.nodes = [];
      for (let i = 0; i < this.nodeCount; i++) {
        this.nodes.push({
          x: Math.random() * this.canvas.width,
          y: Math.random() * this.canvas.height,
          vx: (Math.random() - 0.5) * this.speed,
          vy: (Math.random() - 0.5) * this.speed,
        });
      }
    }

    drawNode(x, y) {
      this.ctx.fillStyle = this.nodeColor;
      this.ctx.beginPath();
      this.ctx.arc(x, y, this.nodeSize, 0, Math.PI * 2);
      this.ctx.fill();
    }

    drawLine(x1, y1, x2, y2, opacity) {
      this.ctx.strokeStyle = `rgba(37, 99, 235, ${opacity * 0.25})`;  /* Более видимые линии */
      this.ctx.lineWidth = this.lineWidth;
      this.ctx.beginPath();
      this.ctx.moveTo(x1, y1);
      this.ctx.lineTo(x2, y2);
      this.ctx.stroke();
    }

    update() {
      // Update node positions
      for (let node of this.nodes) {
        node.x += node.vx;
        node.y += node.vy;

        // Wrap around screen
        if (node.x < 0) node.x = this.canvas.width;
        if (node.x > this.canvas.width) node.x = 0;
        if (node.y < 0) node.y = this.canvas.height;
        if (node.y > this.canvas.height) node.y = 0;
      }
    }

    draw() {
      // Clear canvas
      this.ctx.fillStyle = 'transparent';
      this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

      // Draw connections
      for (let i = 0; i < this.nodes.length; i++) {
        for (let j = i + 1; j < this.nodes.length; j++) {
          const dx = this.nodes[i].x - this.nodes[j].x;
          const dy = this.nodes[i].y - this.nodes[j].y;
          const distance = Math.sqrt(dx * dx + dy * dy);

          if (distance < this.connectionDistance) {
            const opacity = 1 - (distance / this.connectionDistance);
            this.drawLine(
              this.nodes[i].x,
              this.nodes[i].y,
              this.nodes[j].x,
              this.nodes[j].y,
              opacity
            );
          }
        }
      }

      // Draw nodes
      for (let node of this.nodes) {
        this.drawNode(node.x, node.y);
      }
    }

    animate() {
      this.update();
      this.draw();
      this.animationId = requestAnimationFrame(() => this.animate());
    }

    destroy() {
      if (this.animationId) {
        cancelAnimationFrame(this.animationId);
      }
      if (this.canvas) {
        this.canvas.remove();
      }
    }
  }

  // Initialize when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      window.AnimatedGraph = new AnimatedGraph();
    });
  } else {
    window.AnimatedGraph = new AnimatedGraph();
  }
})();
