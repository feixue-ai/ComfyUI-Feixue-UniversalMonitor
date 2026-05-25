/**
 * ============================================================================
 * ComfyUI-Feixue-UniversalMonitor - Animation Utilities
 * ============================================================================
 * 
 * JavaScript 动画工具函数库
 * 提供高性能的动画功能
 * 
 * 包含:
 * - animateValue: 数值滚动动画 (countUp 风格)
 * - springPhysics: 弹簧物理动画
 * - createRipple: Material Design 波纹效果
 * - staggerAnimation: 交错入场动画
 * - ChartAnimator: 图表绘制动画控制器
 * 
 * @author Feixue
 * @version 1.0.0
 * @license MIT
 * ============================================================================
 */

'use strict';

// ============================================================================
// CONFIGURATION (配置)
// ============================================================================

const AnimationConfig = {
  // Duration presets (ms)
  durations: {
    instant: 50,
    fast: 150,
    normal: 300,
    slow: 400,
    slower: 500,
    slowest: 800,
  },
  
  // Easing functions
  easings: {
    linear: (t) => t,
    
    // Quadratic
    easeInQuad: (t) => t * t,
    easeOutQuad: (t) => t * (2 - t),
    easeInOutQuad: (t) => (t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t),
    
    // Cubic
    easeInCubic: (t) => t * t * t,
    easeOutCubic: (t) => (--t) * t * t + 1,
    easeInOutCubic: (t) => (t < 0.5 ? 4 * t * t * t : (t - 1) * (2 * t - 2) * (2 * t - 2) + 1),
    
    // Quartic (for number counting)
    easeInQuart: (t) => t * t * t * t,
    easeOutQuart: (t) => 1 - (--t) * t * t * t,
    easeInOutQuart: (t) => (t < 0.5 ? 8 * t * t * t * t : 1 - 8 * (--t) * t * t * t),
    
    // Special easing
    easeOutBack: (t) => {
      const c1 = 1.70158;
      const c3 = c1 + 1;
      return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2);
    },
    
    easeOutBounce: (t) => {
      const n1 = 7.5625;
      const d1 = 2.75;
      
      if (t < 1 / d1) {
        return n1 * t * t;
      } else if (t < 2 / d1) {
        return n1 * (t -= 1.5 / d1) * t + 0.75;
      } else if (t < 2.5 / d1) {
        return n1 (t -= 2.25 / d1) * t + 0.9375;
      } else {
        return n1 * (t -= 2.625 / d1) * t + 0.984375;
      }
    },
    
    // Spring physics approximation
    spring: (t) => {
      const c4 = (2 * Math.PI) / 3;
      return t === 0 
        ? 0 
        : t === 1 
          ? 1 
          : Math.pow(2, -10 * t) * Math.sin((t * 10 - 0.75) * c4) + 1;
    },
  },
  
  // Check if user prefers reduced motion
  prefersReducedMotion: () => {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }
};

// ============================================================================
// ANIMATE VALUE (数值动画)
// ============================================================================

/**
 * Animate a numeric value from start to end
 * @param {Object} options - Animation options
 * @param {HTMLElement} options.element - Target element to update
 * @param {number} options.start - Start value
 * @param {number} options.end - End value
 * @param {number} [options.duration=300] - Animation duration in ms
 * @param {Function} [options.easing] - Easing function
 * @param {Function} [options.formatter] - Value formatter function
 * @param {Function} [options.onComplete] - Callback when animation completes
 * @returns {Function} Cancel function
 */
function animateValue({
  element,
  start,
  end,
  duration = AnimationConfig.durations.normal,
  easing = AnimationConfig.easings.easeOutQuart,
  formatter = (v) => v.toFixed(1),
  onComplete = null
}) {
  // Skip animation if reduced motion preferred
  if (AnimationConfig.prefersReducedMotion()) {
    if (element) element.textContent = formatter(end);
    if (onComplete) onComplete(end);
    return () => {};
  }
  
  const startTime = performance.now();
  let cancelled = false;
  
  function update(currentTime) {
    if (cancelled) return;
    
    const elapsed = currentTime - startTime;
    const progress = Math.min(elapsed / duration, 1);
    
    const easedProgress = easing(progress);
    const currentValue = start + (end - start) * easedProgress;
    
    if (element) {
      element.textContent = formatter(currentValue);
    }
    
    if (progress < 1) {
      requestAnimationFrame(update);
    } else {
      if (element) element.textContent = formatter(end);
      if (onComplete) onComplete(end);
    }
  }
  
  requestAnimationFrame(update);
  
  // Return cancel function
  return () => { cancelled = true; };
}

/**
 * Animate percentage value with suffix
 */
function animatePercentage(element, targetPercent, duration = 300) {
  const currentText = element.textContent || '0';
  const currentMatch = currentText.match(/[\d.]+/);
  const startValue = currentMatch ? parseFloat(currentMatch[0]) : 0;
  
  return animateValue({
    element,
    start: startValue,
    end: targetPercent,
    duration,
    formatter: (v) => `${v.toFixed(0)}%`
  });
}

// ============================================================================
// SPRING PHYSICS ANIMATION (弹簧物理动画)
// ============================================================================

class SpringAnimation {
  constructor(options = {}) {
    this.stiffness = options.stiffness || 100;     // Spring stiffness
    this.damping = options.damping || 10;           // Damping factor
    this.mass = options.mass || 1;                 // Mass
    this.velocity = 0;
    this.value = options.initialValue || 0;
    this.target = options.target || 0;
    this.onUpdate = options.onUpdate || (() => {});
    this.onRest = options.onRest || (() => {});
    
    this.animationId = null;
    this.isRunning = false;
    this.restThreshold = 0.01;  // Consider at rest when below this
  }
  
  /**
   * Set new target value
   */
  setTarget(target) {
    this.target = target;
    if (!this.isRunning) {
      this.start();
    }
  }
  
  /**
   * Set value immediately (no animation)
   */
  setValue(value) {
    this.value = value;
    this.velocity = 0;
    this.onUpdate(this.value);
  }
  
  /**
   * Start the spring simulation
   */
  start() {
    if (this.isRunning) return;
    
    this.isRunning = true;
    let lastTime = performance.now();
    
    const step = (currentTime) => {
      if (!this.isRunning) return;
      
      const deltaTime = Math.min((currentTime - lastTime) / 1000, 0.064);  // Cap at ~15fps minimum
      lastTime = currentTime;
      
      // Spring force: F = -k * x
      const springForce = -this.stiffness * (this.value - this.target);
      
      // Damping force: F = -c * v
      const dampingForce = -this.damping * this.velocity;
      
      // Acceleration: a = F / m
      const acceleration = (springForce + dampingForce) / this.mass;
      
      // Update velocity and position
      this.velocity += acceleration * deltaTime;
      this.value += this.velocity * deltaTime;
      
      // Check if at rest
      const isAtRest = Math.abs(this.value - this.target) < this.restThreshold &&
                      Math.abs(this.velocity) < this.restThreshold;
      
      if (isAtRest) {
        this.value = this.target;
        this.velocity = 0;
        this.isRunning = false;
        this.onUpdate(this.value);
        this.onRest(this.value);
        return;
      }
      
      this.onUpdate(this.value);
      this.animationId = requestAnimationFrame(step);
    };
    
    this.animationId = requestAnimationFrame(step);
  }
  
  /**
   * Stop the animation
   */
  stop() {
    this.isRunning = false;
    if (this.animationId) {
      cancelAnimationFrame(this.animationId);
      this.animationId = null;
    }
  }
  
  /**
   * Destroy and cleanup
   */
  destroy() {
    this.stop();
    this.onUpdate = () => {};
    this.onRest = () => {};
  }
}

// ============================================================================
// RIPPLE EFFECT (波纹效果)
// ============================================================================

/**
 * Create Material Design ripple effect on click
 * @param {Event} event - Click event
 * @param {HTMLElement} element - Target element
 */
function createRipple(event, element) {
  // Skip if reduced motion
  if (AnimationConfig.prefersReducedMotion()) return;
  
  const rect = element.getBoundingClientRect();
  const size = Math.max(rect.width, rect.height) * 2;
  
  const x = event.clientX - rect.left - size / 2;
  const y = event.clientY - rect.top - size / 2;
  
  const ripple = document.createElement('span');
  ripple.className = 'ripple-effect';
  ripple.style.cssText = `
    position: absolute;
    width: ${size}px;
    height: ${size}px;
    left: ${x}px;
    top: ${y}px;
    background: rgba(0, 212, 255, 0.3);
    border-radius: 50%;
    transform: scale(0);
    animation: ripple 600ms ease-out forwards;
    pointer-events: none;
  `;
  
  // Ensure element has position relative and overflow hidden
  const originalPosition = getComputedStyle(element).position;
  if (originalPosition === 'static') {
    element.style.position = 'relative';
  }
  element.style.overflow = 'hidden';
  
  element.appendChild(ripple);
  
  // Remove ripple after animation
  setTimeout(() => {
    ripple.remove();
    // Restore original styles if no other ripples exist
    if (!element.querySelector('.ripple-effect')) {
      if (originalPosition === 'static') {
        element.style.position = '';
      }
      element.style.overflow = '';
    }
  }, 600);
}

// Initialize ripple on all elements with data-ripple attribute
function initRippleEffects() {
  document.addEventListener('click', (e) => {
    const target = e.target.closest('[data-ripple]');
    if (target) {
      createRipple(e, target);
    }
  });
}

// ============================================================================
// STAGGER ANIMATION (交错动画)
// ============================================================================

/**
 * Staggered entrance animation for child elements
 * @param {HTMLElement} parent - Parent container
 * @param {Object} options - Animation options
 */
function staggerAnimation(parent, options = {}) {
  const {
    selector = ':scope > *, :scope > * > *',
    delay = 50,
    duration = AnimationConfig.durations.slow,
    easing = 'ease-out-back',
    translateY = 10,
    fadeIn = true
  } = options;
  
  // Skip if reduced motion
  if (AnimationConfig.prefersReducedMotion()) return;
  
  const children = parent.querySelectorAll(selector);
  
  children.forEach((child, index) => {
    child.style.opacity = '0';
    child.style.transform = `translateY(${translateY}px)`;
    
    setTimeout(() => {
      child.style.transition = `
        opacity ${duration}ms ${easing},
        transform ${duration}ms ${easing}
      `;
      child.style.opacity = fadeIn ? '1' : '';
      child.style.transform = 'translateY(0)';
    }, index * delay);
  });
}

// ============================================================================
// INTERSECTION OBSERVER FOR LAZY ANIMATIONS (懒加载动画触发器)
// ============================================================================

/**
 * Create intersection observer for triggering animations when elements enter viewport
 * @param {Object} options - Observer options
 * @returns {IntersectionObserver}
 */
function createLazyAnimator(options = {}) {
  const {
    threshold = 0.1,
    rootMargin = '0px 0px -50px 0px',
    onEnter = (el) => {},
    onLeave = (el) => {}
  } = options;
  
  return new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        onEnter(entry.target);
      } else {
        onLeave(entry.target);
      }
    });
  }, {
    threshold,
    rootMargin
  });
}

/**
 * Initialize lazy animations for elements with data-animate attribute
 */
function initLazyAnimations() {
  const animator = createLazyAnimator({
    onEnter: (element) => {
      if (!element.dataset.animated) {
        element.dataset.animated = 'true';
        
        const animationType = element.dataset.animate || 'fadeInUp';
        
        switch (animationType) {
          case 'fadeIn':
            element.style.animation = `fadeIn var(--duration-slow) var(--ease-out-back) both`;
            break;
          case 'fadeInScale':
            element.style.animation = `fadeInScale var(--duration-slow) var(--ease-out-back) both`;
            break;
          case 'slideInRight':
            element.style.animation = `slideInRight var(--duration-slow) var(--ease-out-back) both`;
            break;
          case 'slideInTop':
            element.style.animation = `slideInTop var(--duration-normal) var(--ease-out) both`;
            break;
          case 'stagger':
            staggerAnimation(element);
            break;
          default:
            element.style.animation = `staggerFadeIn var(--duration-slow) var(--ease-out-back) both`;
        }
      }
    }
  });
  
  // Observe all elements with data-animate attribute
  document.querySelectorAll('[data-animate]').forEach(el => {
    animator.observe(el);
  });
  
  return animator;
}

// ============================================================================
// CHART ANIMATOR (图表动画控制器)
// ============================================================================

class ChartAnimator {
  constructor(canvas, options = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    
    this.options = {
      lineColor: options.lineColor || '#00d4ff',
      fillColor: options.fillColor || 'rgba(0, 212, 255, 0.1)',
      lineWidth: options.lineWidth || 2,
      animationDuration: options.animationDuration || AnimationConfig.durations.slower,
      ...options
    };
    
    this.data = [];
    this.animatedData = [];
    this.animationFrame = null;
    this.isAnimating = false;
  }
  
  /**
   * Set chart data with optional animation
   */
  setData(data, animated = true) {
    this.data = data;
    
    if (animated && !AnimationConfig.prefersReducedMotion()) {
      this.animateDataIn();
    } else {
      this.animatedData = [...data];
      this.draw();
    }
  }
  
  /**
   * Animate data drawing in
   */
  animateDataIn() {
    if (this.isAnimating) {
      cancelAnimationFrame(this.animationFrame);
    }
    
    this.isAnimating = true;
    this.animatedData = this.data.map(() => 0);
    
    const startTime = performance.now();
    const duration = this.options.animationDuration;
    
    const animate = (currentTime) => {
      const elapsed = currentTime - startTime;
      const progress = Math.min(elapsed / duration, 1);
      const easedProgress = AnimationConfig.easings.easeOutCubic(progress);
      
      this.animatedData = this.data.map((value, i) => {
        return value * easedProgress;
      });
      
      this.draw();
      
      if (progress < 1) {
        this.animationFrame = requestAnimationFrame(animate);
      } else {
        this.animatedData = [...this.data];
        this.draw();
        this.isAnimating = false;
      }
    };
    
    this.animationFrame = requestAnimationFrame(animate);
  }
  
  /**
   * Draw the chart
   */
  draw() {
    // Override in subclasses or use as base for custom drawing
    const { ctx, canvas, options, animatedData } = this;
    
    const width = canvas.width;
    const height = canvas.height;
    const padding = 20;
    
    // Clear canvas
    ctx.clearRect(0, 0, width, height);
    
    if (animatedData.length === 0) return;
    
    const maxValue = Math.max(...animatedData, 1);
    const minValue = Math.min(...animatedData, 0);
    const range = maxValue - minValue || 1;
    
    const drawWidth = width - padding * 2;
    const drawHeight = height - padding * 2;
    
    // Calculate points
    const points = animatedData.map((value, index) => ({
      x: padding + (index / (animatedData.length - 1 || 1)) * drawWidth,
      y: padding + drawHeight - ((value - minValue) / range) * drawHeight
    }));
    
    // Draw fill gradient
    if (points.length > 1) {
      ctx.beginPath();
      ctx.moveTo(points[0].x, height - padding);
      points.forEach(p => ctx.lineTo(p.x, p.y));
      ctx.lineTo(points[points.length - 1].x, height - padding);
      ctx.closePath();
      
      const gradient = ctx.createLinearGradient(0, padding, 0, height - padding);
      gradient.addColorStop(0, options.fillColor);
      gradient.addColorStop(1, 'transparent');
      ctx.fillStyle = gradient;
      ctx.fill();
    }
    
    // Draw line
    if (points.length > 1) {
      ctx.beginPath();
      ctx.moveTo(points[0].x, points[0].y);
      
      // Catmull-Rom spline interpolation for smooth curves
      for (let i = 0; i < points.length - 1; i++) {
        const p0 = points[Math.max(i - 1, 0)];
        const p1 = points[i];
        const p2 = points[Math.min(i + 1, points.length - 1)];
        const p3 = points[Math.min(i + 2, points.length - 1)];
        
        for (let t = 0; t <= 1; t += 0.1) {
          const x = catmullRom(p0.x, p1.x, p2.x, p3.x, t);
          const y = catmullRom(p0.y, p1.y, p2.y, p3.y, t);
          ctx.lineTo(x, y);
        }
      }
      
      // Create gradient stroke
      const strokeGradient = ctx.createLinearGradient(padding, 0, width - padding, 0);
      strokeGradient.addColorStop(0, '#00d4ff');
      strokeGradient.addColorStop(1, '#a855f7');
      
      ctx.strokeStyle = strokeGradient;
      ctx.lineWidth = options.lineWidth;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.stroke();
    }
  }
  
  /**
   * Clear and stop animation
   */
  destroy() {
    if (this.animationFrame) {
      cancelAnimationFrame(this.animationFrame);
    }
    this.isAnimating = false;
  }
}

// Catmull-Rom spline interpolation helper
function catmullRom(p0, p1, p2, p3, t) {
  const t2 = t * t;
  const t3 = t2 * t;
  return 0.5 * (
    (2 * p1) +
    (-p0 + p2) * t +
    (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 +
    (-p0 + 3 * p1 - 3 * p2 + p3) * t3
  );
}

// ============================================================================
// UTILITY FUNCTIONS (工具函数)
// ============================================================================

/**
 * Debounce function calls
 */
function debounce(func, wait = 16) {
  let timeout;
  return function executedFunction(...args) {
    const later = () => {
      clearTimeout(timeout);
      func(...args);
    };
    clearTimeout(timeout);
    timeout = setTimeout(later, wait);
  };
}

/**
 * Throttle function calls
 */
function throttle(func, limit = 16) {
  let inThrottle;
  return function executedFunction(...args) {
    if (!inThrottle) {
      func.apply(this, args);
      inThrottle = true;
      setTimeout(() => inThrottle = false, limit);
    }
  };
}

/**
 * Lerp between two values
 */
function lerp(start, end, t) {
  return start + (end - start) * t;
}

/**
 * Lerp between two colors (hex)
 */
function lerpColor(color1, color2, t) {
  const c1 = hexToRgb(color1);
  const c2 = hexToRgb(color2);
  
  if (!c1 || !c2) return color1;
  
  const r = Math.round(lerp(c1.r, c2.r, t));
  const g = Math.round(lerp(c1.g, c2.g, t));
  const b = Math.round(lerp(c1.b, c2.b, t));
  
  return rgbToHex(r, g, b);
}

function hexToRgb(hex) {
  const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
  return result ? {
    r: parseInt(result[1], 16),
    g: parseInt(result[2], 16),
    b: parseInt(result[3], 16)
  } : null;
}

function rgbToHex(r, g, b) {
  return '#' + [r, g, b].map(x => {
    const hex = x.toString(16);
    return hex.length === 1 ? '0' + hex : hex;
  }).join('');
}

// ============================================================================
// EXPORTS (导出)
// ============================================================================

// Export for ES modules
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    AnimationConfig,
    animateValue,
    animatePercentage,
    SpringAnimation,
    createRipple,
    initRippleEffects,
    staggerAnimation,
    createLazyAnimator,
    initLazyAnimations,
    ChartAnimator,
    debounce,
    throttle,
    lerp,
    lerpColor
  };
}
