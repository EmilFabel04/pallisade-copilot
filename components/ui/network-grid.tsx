'use client';

import * as React from 'react';

interface Node {
  x: number;
  y: number;
  connections: number[];
}

export function NetworkGrid() {
  const canvasRef = React.useRef<HTMLCanvasElement>(null);
  const animationRef = React.useRef<number>(0);
  const nodesRef = React.useRef<Node[]>([]);
  const scanAngleRef = React.useRef(0);
  const threatNodesRef = React.useRef<Set<number>>(new Set());
  const secureNodesRef = React.useRef<Set<number>>(new Set());
  const lastThreatTimeRef = React.useRef(0);

  React.useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Set canvas size
    const resize = () => {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
      generateNodes();
    };

    // Generate network nodes
    const generateNodes = () => {
      const nodes: Node[] = [];
      const cols = Math.ceil(canvas.width / 120);
      const rows = Math.ceil(canvas.height / 120);
      const spacingX = canvas.width / cols;
      const spacingY = canvas.height / rows;

      for (let row = 0; row <= rows; row++) {
        for (let col = 0; col <= cols; col++) {
          const x = col * spacingX + (Math.random() - 0.5) * 40;
          const y = row * spacingY + (Math.random() - 0.5) * 40;
          nodes.push({ x, y, connections: [] });
        }
      }

      // Create connections to nearby nodes
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const dx = nodes[i].x - nodes[j].x;
          const dy = nodes[i].y - nodes[j].y;
          const dist = Math.sqrt(dx * dx + dy * dy);
          if (dist < 180 && Math.random() > 0.3) {
            nodes[i].connections.push(j);
          }
        }
      }

      nodesRef.current = nodes;
    };

    // Animation loop
    const animate = (time: number) => {
      if (!ctx || !canvas) return;

      ctx.clearRect(0, 0, canvas.width, canvas.height);

      const nodes = nodesRef.current;
      const centerX = canvas.width / 2;
      const centerY = canvas.height / 2;

      // Update scan angle (slow rotation)
      scanAngleRef.current += 0.008;
      if (scanAngleRef.current > Math.PI * 2) {
        scanAngleRef.current -= Math.PI * 2;
      }

      // Occasionally mark random nodes as threats or secure
      if (time - lastThreatTimeRef.current > 2000) {
        lastThreatTimeRef.current = time;
        
        // Clear old statuses
        if (Math.random() > 0.7) {
          threatNodesRef.current.clear();
          secureNodesRef.current.clear();
        }

        // Add new threat (rare)
        if (Math.random() > 0.85) {
          const randomNode = Math.floor(Math.random() * nodes.length);
          threatNodesRef.current.add(randomNode);
        }

        // Add secure nodes (more common)
        if (Math.random() > 0.5) {
          const randomNode = Math.floor(Math.random() * nodes.length);
          if (!threatNodesRef.current.has(randomNode)) {
            secureNodesRef.current.add(randomNode);
          }
        }
      }

      // Draw connections
      ctx.lineWidth = 1;
      for (let i = 0; i < nodes.length; i++) {
        const node = nodes[i];
        for (const j of node.connections) {
          const other = nodes[j];
          
          // Calculate if connection is in scan beam
          const midX = (node.x + other.x) / 2;
          const midY = (node.y + other.y) / 2;
          const angleToMid = Math.atan2(midY - centerY, midX - centerX);
          const angleDiff = Math.abs(normalizeAngle(angleToMid - scanAngleRef.current));
          const inBeam = angleDiff < 0.3;

          if (inBeam) {
            ctx.strokeStyle = 'rgba(139, 11, 16, 0.4)';
          } else {
            ctx.strokeStyle = 'rgba(139, 11, 16, 0.08)';
          }

          ctx.beginPath();
          ctx.moveTo(node.x, node.y);
          ctx.lineTo(other.x, other.y);
          ctx.stroke();
        }
      }

      // Draw scan beam (radar sweep)
      const gradient = ctx.createConicGradient(scanAngleRef.current, centerX, centerY);
      gradient.addColorStop(0, 'rgba(139, 11, 16, 0.15)');
      gradient.addColorStop(0.05, 'rgba(139, 11, 16, 0.08)');
      gradient.addColorStop(0.1, 'rgba(139, 11, 16, 0)');
      gradient.addColorStop(1, 'rgba(139, 11, 16, 0)');

      ctx.fillStyle = gradient;
      ctx.beginPath();
      ctx.arc(centerX, centerY, Math.max(canvas.width, canvas.height), 0, Math.PI * 2);
      ctx.fill();

      // Draw nodes
      for (let i = 0; i < nodes.length; i++) {
        const node = nodes[i];
        
        // Calculate if node is in scan beam
        const angleToNode = Math.atan2(node.y - centerY, node.x - centerX);
        const angleDiff = Math.abs(normalizeAngle(angleToNode - scanAngleRef.current));
        const inBeam = angleDiff < 0.15;
        const recentlyScanned = angleDiff < 0.5 && angleDiff > 0.15;

        const isThreat = threatNodesRef.current.has(i);
        const isSecure = secureNodesRef.current.has(i);

        // Node glow
        if (isThreat) {
          // Threat node - pulsing red
          const pulse = Math.sin(time * 0.005) * 0.5 + 0.5;
          ctx.shadowColor = 'rgba(255, 50, 50, 0.8)';
          ctx.shadowBlur = 15 + pulse * 10;
          ctx.fillStyle = `rgba(255, 50, 50, ${0.6 + pulse * 0.4})`;
        } else if (isSecure) {
          // Secure node - steady green
          ctx.shadowColor = 'rgba(50, 205, 50, 0.6)';
          ctx.shadowBlur = 10;
          ctx.fillStyle = 'rgba(50, 205, 50, 0.7)';
        } else if (inBeam) {
          // Currently being scanned
          ctx.shadowColor = 'rgba(196, 30, 36, 0.8)';
          ctx.shadowBlur = 20;
          ctx.fillStyle = 'rgba(196, 30, 36, 0.9)';
        } else if (recentlyScanned) {
          // Recently scanned fade
          const fade = 1 - (angleDiff - 0.15) / 0.35;
          ctx.shadowColor = `rgba(139, 11, 16, ${0.5 * fade})`;
          ctx.shadowBlur = 10 * fade;
          ctx.fillStyle = `rgba(139, 11, 16, ${0.3 + 0.4 * fade})`;
        } else {
          // Idle node
          ctx.shadowColor = 'transparent';
          ctx.shadowBlur = 0;
          ctx.fillStyle = 'rgba(139, 11, 16, 0.25)';
        }

        ctx.beginPath();
        ctx.arc(node.x, node.y, isThreat || isSecure ? 5 : inBeam ? 4 : 3, 0, Math.PI * 2);
        ctx.fill();

        // Reset shadow
        ctx.shadowColor = 'transparent';
        ctx.shadowBlur = 0;
      }

      // Draw center point (command center)
      ctx.fillStyle = 'rgba(139, 11, 16, 0.6)';
      ctx.beginPath();
      ctx.arc(centerX, centerY, 6, 0, Math.PI * 2);
      ctx.fill();

      // Outer ring
      ctx.strokeStyle = 'rgba(139, 11, 16, 0.2)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.arc(centerX, centerY, 12, 0, Math.PI * 2);
      ctx.stroke();

      animationRef.current = requestAnimationFrame(animate);
    };

    const normalizeAngle = (angle: number) => {
      while (angle > Math.PI) angle -= Math.PI * 2;
      while (angle < -Math.PI) angle += Math.PI * 2;
      return angle;
    };

    resize();
    window.addEventListener('resize', resize);
    animationRef.current = requestAnimationFrame(animate);

    return () => {
      window.removeEventListener('resize', resize);
      cancelAnimationFrame(animationRef.current);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className="fixed inset-0 z-[-1] pointer-events-none"
      style={{ opacity: 0.6 }}
    />
  );
}

