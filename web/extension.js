/**
 * ComfyUI-Feixue-UniversalMonitor - 紧急救援版
 * 
 * 纯IIFE实现，无ES6模块依赖
 * 兼容所有ComfyUI版本
 * 
 * @version 1.0.0-Emergency
 */

(function() {
    'use strict';

    console.log('[飞雪监测器] 🚀 紧急救援版启动...');

    // ============================================================
    // 配置常量
    // ============================================================
    const CONFIG = {
        version: '1.0.0-Emergency',
        updateInterval: 2000,
        position: { top: '10px', right: '10px' },
        theme: {
            cyberpunk: {
                bg: 'rgba(0, 0, 0, 0.85)',
                border: '#00ffff',
                text: '#00ff00',
                glow: '0 0 15px rgba(0, 255, 255, 0.5)'
            }
        },
        // 方案配置 (scheme-a / scheme-b / scheme-c)
        currentScheme: 'scheme-a',  // 默认使用方案A（极简主义专业版）
        availableSchemes: ['scheme-a', 'scheme-b', 'scheme-c'],
        schemeLabels: {
            'scheme-a': { label: 'A', title: '极简主义 (Minimalist Pro)', desc: '扁平化/高可读性' },
            'scheme-b': { label: 'B', title: '科技未来 (Cyberpunk Tech)', desc: '霓虹发光/切角造型/扫描线' },
            'scheme-c': { label: 'C', title: '玻璃精致 (Glassmorphism)', desc: '毛玻璃模糊/大圆角/精致质感' }
        }
    };

    // ============================================================
    // 主题系统 - 预设主题配置
    // ============================================================
    const THEMES = [
        {
            name: 'Cyberpunk Blue',
            primaryColor: '#00ffff',
            secondaryColor: '#0088ff',
            bgColor: 'rgba(0, 10, 20, 0.92)',
            textColor: '#00ff00',
            glowColor: 'rgba(0, 255, 255, 0.5)',
            borderColor: '#00ffff',
            buttonGradient: 'linear-gradient(135deg, #00d4ff 0%, #0088ff 100%)'
        },
        {
            name: 'Neon Purple',
            primaryColor: '#bf00ff',
            secondaryColor: '#8b00ff',
            bgColor: 'rgba(15, 5, 25, 0.92)',
            textColor: '#e0a0ff',
            glowColor: 'rgba(191, 0, 255, 0.5)',
            borderColor: '#bf00ff',
            buttonGradient: 'linear-gradient(135deg, #bf00ff 0%, #8b00ff 100%)'
        },
        {
            name: 'Matrix Green',
            primaryColor: '#00ff41',
            secondaryColor: '#00cc33',
            bgColor: 'rgba(0, 5, 2, 0.95)',
            textColor: '#00ff41',
            glowColor: 'rgba(0, 255, 65, 0.4)',
            borderColor: '#00ff41',
            buttonGradient: 'linear-gradient(135deg, #00ff41 0%, #00cc33 100%)'
        }
    ];
    let currentThemeIndex = 0;

    // ============================================================
    // 性能/节能模式系统 (Task 4)
    // ============================================================
    let performanceMode = true; // 默认开启性能模式

    /**
     * 辅助函数: 将十六进制颜色转换为 rgba 格式
     * 用于 3D 立体效果的主题色动态适配
     * 
     * @param {string} hex - 十六进制颜色值 (如 '#00ff41' 或 '00ff41')
     * @param {number} alpha - 透明度 (0-1)
     * @returns {string} rgba 格式颜色字符串
     */
    function hexToRgba(hex, alpha) {
        // 移除 # 号
        hex = String(hex).replace('#', '');
        
        // 处理 3 位简写格式 (如 #0f0 -> #00ff00)
        if (hex.length === 3) {
            hex = hex.split('').map(function(c) { return c + c; }).join('');
        }
        
        // 解析 RGB 分量
        const r = parseInt(hex.substring(0, 2), 16) || 0;
        const g = parseInt(hex.substring(2, 4), 16) || 0;
        const b = parseInt(hex.substring(4, 6), 16) || 0;
        
        // 确保 alpha 在有效范围内
        const a = Math.max(0, Math.min(1, parseFloat(alpha) || 1));
        
        return `rgba(${r}, ${g}, ${b}, ${a})`;
    }

    /**
     * 提亮颜色 (增加亮度) - 用于 3D 立体效果的主题色动态适配
     * @param {string} hex - 十六进制颜色值 (如 '#00ff41')
     * @param {number} percent - 提亮百分比 0-100 (默认30)
     * @returns {string} 更亮的十六进制颜色
     */
    function lightenColor(hex, percent) {
        if (!hex || hex === 'transparent') return '#ffffff';
        percent = percent || 30;

        hex = String(hex).replace('#', '');
        if (hex.length === 3) {
            hex = hex.split('').map(function(c) { return c + c; }).join('');
        }

        var r = parseInt(hex.substring(0, 2), 16) || 0;
        var g = parseInt(hex.substring(2, 4), 16) || 0;
        var b = parseInt(hex.substring(4, 6), 16) || 0;

        // 向白色(255)靠近
        r = Math.min(255, Math.floor(r + (255 - r) * percent / 100));
        g = Math.min(255, Math.floor(g + (255 - g) * percent / 100));
        b = Math.min(255, Math.floor(b + (255 - b) * percent / 100));

        return '#' + [r, g, b].map(function(x) {
            return x.toString(16).padStart(2, '0');
        }).join('');
    }

    /**
     * 解析颜色字符串为 RGB 对象
     * 支持 '#RRGGBB' 或 'rgb(r,g,b)' 或 'rgba(r,g,b,a)' 格式
     * @param {string} colorStr - 颜色字符串
     * @returns {{r:number, g:number, b:number}} RGB 分量对象
     */
    function parseRgb(colorStr) {
        if (!colorStr) return { r: 128, g: 128, b: 128 };
        var match = colorStr.match(/\d+/g);
        if (match && match.length >= 3) {
            return {
                r: parseInt(match[0], 10) || 0,
                g: parseInt(match[1], 10) || 0,
                b: parseInt(match[2], 10) || 0
            };
        }
        // 尝试解析 hex 格式
        var hex = String(colorStr).replace('#', '');
        if (hex.length === 3) {
            hex = hex.split('').map(function(c) { return c + c; }).join('');
        }
        if (hex.length === 6 && /^[0-9a-fA-F]+$/.test(hex)) {
            return {
                r: parseInt(hex.substring(0, 2), 16) || 0,
                g: parseInt(hex.substring(2, 4), 16) || 0,
                b: parseInt(hex.substring(4, 6), 16) || 0
            };
        }
        return { r: 128, g: 128, b: 128 };  // 默认灰色
    }

    /**
     * 混合两个颜色 - 用于背景渐变融入主题色调
     * @param {string} color1 - 颜色1 (支持 hex 或 rgb())
     * @param {string} color2 - 颜色2 (基础色)
     * @param {number} ratio - color1 的混合比例 0-1 (color1占比)
     * @returns {string} rgb() 颜色字符串
     */
    function mixColor(color1, color2, ratio) {
        var c1 = parseRgb(color1);
        var c2 = parseRgb(color2);

        var r = Math.round(c1.r + (c2.r - c1.r) * ratio);
        var g = Math.round(c1.g + (c2.g - c1.g) * ratio);
        var b = Math.round(c1.b + (c2.b - c1.b) * ratio);

        return 'rgb(' + r + ',' + g + ',' + b + ')';
    }

    /**
     * 创建模式切换开关 - 圆形iOS风格toggle
     * @returns {HTMLElement} 模式切换按钮元素
     */
    function createModeToggle() {
        const toggle = document.createElement('div');
        toggle.className = 'fxm-mode-toggle';
        toggle.id = 'fxm-mode-toggle';
        toggle.innerHTML = '⚡'; // 性能模式图标
        toggle.title = '性能模式：开启所有视觉效果';

        // 初始样式（基于当前模式状态）
        Object.assign(toggle.style, {
            width: '24px',
            height: '24px',
            borderRadius: '50%',
            background: performanceMode
                ? 'radial-gradient(circle, #00ff41 0%, #00cc33 100%)'
                : 'radial-gradient(circle, #888888 0%, #666666 100%)',
            boxShadow: performanceMode
                ? '0 0 10px rgba(0, 255, 65, 0.5)'
                : 'none',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: '12px',
            color: '#000',
            fontWeight: 'bold',
            transition: 'all 0.3s ease',
            marginRight: '8px', // 与主题按钮的间距
            flexShrink: '0',
        });

        // 点击事件 - 切换模式
        toggle.addEventListener('click', function(e) {
            e.stopPropagation(); // 阻止事件冒泡

            performanceMode = !performanceMode;
            applyPerformanceMode(performanceMode);

            // 更新按钮外观
            if (performanceMode) {
                toggle.innerHTML = '⚡';
                toggle.style.background = 'radial-gradient(circle, #00ff41 0%, #00cc33 100%)';
                toggle.style.boxShadow = '0 0 10px rgba(0, 255, 65, 0.5)';
                toggle.title = '性能模式：开启所有视觉效果';
            } else {
                toggle.innerHTML = '🍃';
                toggle.style.background = 'radial-gradient(circle, #888888 0%, #666666 100%)';
                toggle.style.boxShadow = 'none';
                toggle.title = '节能模式：简化视觉效果以节省资源';
            }

            // 保存到 localStorage
            try {
                localStorage.setItem('fxm-performance-mode', String(performanceMode));
            } catch (e) {
                // localStorage 不可用时静默失败
            }

            console.log(`[飞雪监测器] 模式切换: ${performanceMode ? '⚡ 性能' : '🍃 节能'}`);
        });

        return toggle;
    }

    /**
     * 创建方案切换按钮组 - A/B/C三套视觉风格选择器
     * 
     * **设计规格**:
     * - 尺寸: 24px x 24px 小型圆角方形
     * - 字体: 11px bold 居中显示 A/B/C
     * - 默认态: 半透明背景 rgba(255,255,255,0.08)
     * - 悬停态: 背景提亮 + 显示tooltip
     * - 选中态: 主题色边框(2px) + 背景色填充 + 发光效果
     * 
     * @returns {HTMLElement} 方案切换按钮组容器
     */
    function createSchemeSwitcher() {
        const container = document.createElement('div');
        container.className = 'fxm-scheme-switcher';
        container.id = 'fxm-scheme-switcher';
        container.title = '视觉方案切换 (A:极简 / B:科技 / C:玻璃)';

        // 基础容器样式
        Object.assign(container.style, {
            display: 'flex',
            alignItems: 'center',
            gap: '4px',
            padding: '3px',
            background: 'rgba(0, 0, 0, 0.3)',
            borderRadius: '8px',
            border: '1px solid rgba(255, 255, 255, 0.1)',
            marginLeft: '8px', // 与左侧按钮的间距
            flexShrink: '0',
        });

        // 创建三个方案按钮
        CONFIG.availableSchemes.forEach(function(scheme) {
            const labelInfo = CONFIG.schemeLabels[scheme];
            const btn = document.createElement('button');
            btn.className = 'fxm-scheme-btn' + (scheme === CONFIG.currentScheme ? ' active' : '');
            btn.dataset.scheme = scheme;
            btn.title = labelInfo.title;

            // 按钮基础样式
            Object.assign(btn.style, {
                width: '24px',
                height: '24px',
                borderRadius: '6px',
                border: '2px solid transparent',
                background: scheme === CONFIG.currentScheme 
                    ? 'rgba(0, 255, 255, 0.2)' 
                    : 'rgba(255, 255, 255, 0.08)',
                color: '#ffffff',
                fontSize: '11px',
                fontWeight: 'bold',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                transition: 'all 0.25s cubic-bezier(0.16, 1, 0.3, 1)',
                outline: 'none',
                fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
                letterSpacing: '0',
                userSelect: 'none',
                position: 'relative',
                overflow: 'hidden',
            });

            // 选中态特殊样式
            if (scheme === CONFIG.currentScheme) {
                btn.style.borderColor = 'var(--fxm-primary-color, #00ffff)';
                btn.style.boxShadow = '0 0 8px rgba(0, 255, 255, 0.4)';
            }

            // 按钮标签
            const labelSpan = document.createElement('span');
            labelSpan.className = 'fxm-scheme-btn__label';
            labelSpan.textContent = labelInfo.label;
            labelSpan.style.cssText = `
                line-height: 1;
                pointer-events: none;
            `;
            btn.appendChild(labelSpan);

            // 点击事件 - 切换方案
            btn.addEventListener('click', function(e) {
                e.stopPropagation(); // 防止事件冒泡到面板
                const targetScheme = btn.dataset.scheme;
                console.log('[飞雪] 🎨 用户点击方案按钮: ' + targetScheme);
                switchUIScheme(targetScheme);
            });

            // 悬停增强效果
            btn.addEventListener('mouseenter', function() {
                if (!btn.classList.contains('active')) {
                    btn.style.background = 'rgba(255, 255, 255, 0.15)';
                    btn.style.transform = 'scale(1.08)';
                }
            });

            btn.addEventListener('mouseleave', function() {
                if (!btn.classList.contains('active')) {
                    btn.style.background = 'rgba(255, 255, 255, 0.08)';
                    btn.style.transform = 'scale(1)';
                }
            });

            container.appendChild(btn);
        });

        console.log('[飞雪] ✅ 方案切换按钮组已创建 (A/B/C)');
        return container;
    }

    /**
     * 应用性能/节能模式 - 控制资源消耗和视觉效果 (Task 6 增强: 3D 立体效果)
     * 
     * **设计原则**:
     * - 性能模式: 多层 box-shadow + 渐变背景 + hover 微浮起 = 3D 凸起质感
     * - 节能模式: 单层阴影 + 纯色背景 + 无动画 = 扁平简化
     * - 所有颜色从 CSS 变量动态读取,支持主题适配
     * 
     * @param {boolean} isPerformance - true=性能模式, false=节能模式
     */
    function applyPerformanceMode(isPerformance) {
        const root = document.documentElement;
        const panel = document.getElementById('fxm-hover-panel');
        const capsules = document.querySelectorAll('.fxm-capsule');

        // 获取当前主题颜色（用于 3D 效果的动态配色）
        const rootStyles = getComputedStyle(root);
        const themeColor = rootStyles.getPropertyValue('--fxm-primary').trim() || '#00ff41';
        const bgColorPrimary = rootStyles.getPropertyValue('--fxm-bg').trim() || 'rgba(0, 10, 20, 0.92)';

        if (isPerformance) {
            // ===== 性能模式: 3D 立体凸起效果 =====
            CONFIG.updateInterval = 2000; // 2秒刷新

            // 启用毛玻璃效果
            if (panel) {
                panel.style.backdropFilter = 'blur(20px) saturate(180%)';
                panel.style.webkitBackdropFilter = 'blur(20px) saturate(180%)';
                // 保持主题背景色但增加透明度以显示毛玻璃效果
                const currentBg = getComputedStyle(root).getPropertyValue('--fxm-bg').trim();
                if (currentBg) {
                    panel.style.background = currentBg.replace(/[\d.]+\)$/, '0.85)');
                } else {
                    panel.style.background = 'rgba(10, 14, 23, 0.85)';
                }
            }

            // 启用 3D 立体效果（多层阴影 + 渐变背景 + hover 动画）
            capsules.forEach(function(cap) {
                // 添加性能模式标识类名
                cap.classList.add('enhanced');
                cap.classList.remove('simple');

                // ★ Scheme A 支持: 极简主义胶囊使用CSS类控制样式 ★
                if (cap.classList.contains('scheme-a')) {
                    // Scheme A: 性能模式下仅添加极浅阴影和边框高亮（克制差异）
                    // 核心样式已由 .fxm-capsule.scheme-a.enhanced CSS类控制
                    // 不设置内联样式，保持CSS驱动的极简风格
                    cap.style.boxShadow = '';  // 清空内联样式，使用CSS类
                    cap.style.background = '';  // 清空内联样式，使用CSS类
                    cap.style.borderColor = '';  // 清空内联样式，使用CSS类
                    cap.style.transition = '';   // 清空内联样式，使用CSS类
                    return;  // 跳过后续的复杂样式设置
                }

                // ★★★ 定向光源砖块风格阴影系统 (Directional Light Brick) ★★★
                // 光源位置: 左上方 → 左侧/顶部高光，右侧/底部暗边
                // ★ 核心改进: 所有高光颜色从 themeColor 动态生成，随主题变化!
                var tc = themeColor;  // 简写引用

                cap.style.boxShadow =
                    /* 1. 主投影: 向右下 (模拟左上光源投射阴影) */
                    '5px 7px 14px rgba(0, 0, 0, 0.65), ' +
                    /* 2. ★ 左侧高光: 使用主题色的亮版本! */
                    '-5px 0 10px ' + hexToRgba(lightenColor(tc, 40), 0.45) + ', ' +
                    /* 3. 顶部高光: 使用主题色的浅版本! */
                    '0 -4px 10px ' + hexToRgba(lightenColor(tc, 20), 0.25) + ', ' +
                    /* 4. 内顶部反光 (受光面) */
                    'inset 0 2px 0 rgba(255, 255, 255, 0.28), ' +
                    /* 5. 内底部暗边 (背光面) */
                    'inset 0 -2px 0 rgba(0, 0, 0, 0.45), ' +
                    /* 6. 内右侧暗边 (背光面) */
                    'inset -3px 0 4px rgba(0, 0, 0, 0.25)';

                // 渐变背景模拟砖块体积感（135度对角渐变，融入主题色调）
                cap.style.background = 'linear-gradient(' +
                    '135deg, ' +
                    mixColor(tc, 'rgb(45,50,75)', 0.15) + ' 0%, ' +     /* 混入15%主题色 */
                    mixColor(tc, 'rgb(28,33,52)', 0.10) + ' 50%, ' +     /* 混入10%主题色 */
                    mixColor(tc, 'rgb(18,22,38)', 0.05) + ' 100%' +     /* 混入5%主题色 */
                ')';

                // 边框: 使用主题色（带透明度），替代硬编码白色
                cap.style.borderColor = hexToRgba(themeColor, 0.35);

                // 启用 GPU 加速的过渡动画（transform + box-shadow）
                cap.style.transition = 'transform 0.25s ease, box-shadow 0.25s ease';

                // 启用 hover 微浮起效果（通过 data 属性标记）
                cap.dataset.performanceMode = 'true';
            });

            // Task 3: 性能模式 - 增强底盘视觉效果（截图2风格）
            const tray = document.getElementById('fxm-capsule-tray');
            if (tray) {
                tray.classList.add('enhanced');
                tray.classList.remove('simple');
                tray.style.boxShadow =
                    'inset 0 3px 8px rgba(0, 0, 0, 0.7), ' +   /* 更深凹陷 */
                    '0 6px 20px ' + hexToRgba(themeColor, 0.2); /* 更强外影+主题色微发光 */
                console.log('[飞雪监测器]   底盘已增强: 深凹陷 + 主题色微发光 (截图2风格)');
            }

            console.log('[飞雪监测器] ⚡ 性能模式已启用：定向光源砖块立体+毛玻璃+动画+底盘增强');

        } else {
            // ===== 节能模式: 扁平简化效果 =====
            CONFIG.updateInterval = 5000; // 5秒刷新

            // 关闭毛玻璃效果
            if (panel) {
                panel.style.backdropFilter = 'none';
                panel.style.webkitBackdropFilter = 'none';
                panel.style.background = 'rgba(20, 20, 30, 0.95)';
            }

            // 关闭复杂动画和阴影（单层扁平）
            capsules.forEach(function(cap) {
                // 添加节能模式标识类名
                cap.classList.remove('enhanced');
                cap.classList.add('simple');

                // ★ Scheme A 支持: 极简主义胶囊使用CSS类控制样式 ★
                if (cap.classList.contains('scheme-a')) {
                    // Scheme A: 节能模式下完全移除阴影和边框，保持极简
                    // 核心样式已由 .fxm-capsule.scheme-a.simple CSS类控制
                    cap.style.boxShadow = '';  // 清空内联样式，使用CSS类
                    cap.style.background = '';  // 清空内联样式，使用CSS类
                    cap.style.borderColor = '';  // 清空内联样式，使用CSS类
                    cap.style.transition = '';   // 清空内联样式，使用CSS类
                    cap.dataset.performanceMode = 'false';
                    return;  // 跳过后续的样式设置
                }

                // 单层简单阴影（仅基础深度感）
                cap.style.boxShadow = '0 2px 4px rgba(0, 0, 0, 0.3)';

                // 纯色背景（无渐变，降低渲染成本）
                cap.style.background = 'rgba(30, 30, 40, 0.95)';

                // 禁用所有过渡动画（节省 GPU 资源）
                cap.style.transition = 'none';

                // 标记为节能模式
                cap.dataset.performanceMode = 'false';
            });

            // Task 3: 节能模式 - 简化底盘视觉效果
            const tray = document.getElementById('fxm-capsule-tray');
            if (tray) {
                tray.classList.remove('enhanced');
                tray.classList.add('simple');
                tray.style.boxShadow = 'inset 0 2px 4px rgba(0, 0, 0, 0.5)';
                console.log('[飞雪监测器]   底盘已简化: 仅保留基础内阴影');
            }

            console.log('[飞雪监测器] 🍃 节能模式已启用：扁平化+关闭特效+底盘简化');
        }

        // 应用CSS变量供其他组件使用
        root.style.setProperty('--fxm-performance-mode', isPerformance ? '1' : '0');

        // 重启数据采集定时器以应用新的刷新间隔
        stopDataCollection();
        startDataCollection();
    }

    /**
     * ⚠️ 已废弃 - updateCapsuleThemeColors()
     *
     * **废弃原因 (Task 1 解耦重构)**:
     * 该函数内部设置了 capsule.style.background 和 capsule.style.boxShadow，
     * 这严重违反了"主题与模式系统完全解耦"的核心原则。
     *
     * **违规操作**:
     * ❌ cap.style.boxShadow = ... (原第329行)
     * ❌ cap.style.background = ... (原第342行)
     *
     * **正确的解耦架构**:
     * - 主题系统 (applyTheme()): 只设置 CSS 变量，绝对不碰 inline style
     * - 模式系统 (applyPerformanceMode()): 读取 CSS 变量，自己决定视觉效果
     * - 两者通过 CSS 变量间接通信，零直接调用
     *
     * **替代方案**:
     * 当用户切换主题时，applyTheme() 会更新 CSS 变量（如 --fxm-primary）。
     * 下次 applyPerformanceMode() 执行时（或用户手动切换模式时），
     * 它会通过 getComputedStyle() 读取最新的主题色，自动应用新颜色。
     *
     * @deprecated since v1.0.1 - 违反解耦原则，已从 applyTheme() 中移除调用
     */
    function updateCapsuleThemeColors() {
        // ✅ 空实现 - 不再执行任何操作
        // 原因: 避免意外修改 capsule 的 background/boxShadow 属性
        console.log('[飞雪监测器] ⚠️ updateCapsuleThemeColors() 已废弃，调用被忽略');
    }

    /**
     * 从 localStorage 加载用户偏好设置
     */
    function loadUserPreferences() {
        try {
            const savedMode = localStorage.getItem('fxm-performance-mode');
            if (savedMode !== null) {
                performanceMode = savedMode === 'true';
                // 应用模式但不更新UI（因为UI还未创建）
                // 只更新配置值
                if (!performanceMode) {
                    CONFIG.updateInterval = 5000; // 节能模式使用5秒间隔
                }
                console.log(`[飞雪监测器] 恢复用户偏好: ${performanceMode ? '性能' : '节能'}模式`);
            }
        } catch (e) {
            // localStorage 不可用时静默失败
        }
    }

    // ============================================================
    // PRED 预测开关状态（Task 5 实现）
    // ============================================================
    let predEnabled = false;  // 默认关闭 - 用户主动选择才启用

    // ============================================================
    // PRED 预测开关 UI 组件（Task 5 实现）
    // ============================================================

    /**
     * 创建 iOS 风格的 PRED 预测开关
     * @returns {HTMLDivElement} 开关容器元素
     */
    function createPredToggle() {
        // 增强初始化日志 (Step 2.4)
        console.log('[飞雪监测器] 🎮 创建 PRED Toggle');
        console.log(`[飞雪监测器]   初始 predEnabled = ${predEnabled} (来源: localStorage)`);
        console.log(`[飞雪监测器]   将使用延迟绑定 (requestAnimationFrame)`);

        const container = document.createElement('div');
        container.className = 'fxm-pred-toggle-container';
        container.style.cssText = `
            display: flex;
            align-items: center;
            gap: 6px;
            position: absolute;
            top: 10px;
            right: 10px;
        `;

        // 标签
        const label = document.createElement('span');
        label.textContent = 'PRED';
        label.style.cssText = `
            font-size: 11px;
            font-weight: 600;
            color: var(--fxm-text-color, #ccc);
            opacity: 0.7;
        `;

        // 开关本体
        const toggle = document.createElement('div');
        toggle.className = 'fxm-pred-toggle';
        toggle.id = 'fxm-pred-toggle';

        // 初始状态样式（OFF）
        Object.assign(toggle.style, {
            width: '44px',
            height: '24px',
            borderRadius: '12px',
            background: '#555555',
            position: 'relative',
            cursor: 'pointer',
            transition: 'background 0.2s ease-in-out',
            boxShadow: 'inset 0 1px 3px rgba(0,0,0,0.3)',
        });

        // 滑块
        const knob = document.createElement('div');
        knob.className = 'fxm-pred-knob';
        Object.assign(knob.style, {
            width: '18px',
            height: '18px',
            borderRadius: '50%',
            background: '#ffffff',
            position: 'absolute',
            top: '3px',
            left: '3px',
            transition: 'transform 0.2s ease-in-out',
            boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
        });

        toggle.appendChild(knob);
        container.appendChild(label);
        container.appendChild(toggle);

        // 双击防抖变量 (Step 2.3)
        let lastPredClickTime = 0;
        const PRED_DEBOUNCE_MS = 200; // 200ms防抖窗口

        // 点击事件 - 使用命名函数便于调试和移除（增强版：防抖+详细日志）
        function handlePredToggleClick(e) {
            // 防抖检查 - 忽略过快点击 (Step 2.3)
            const now = Date.now();
            if (now - lastPredClickTime < PRED_DEBOUNCE_MS) {
                console.log('[飞雪监测器] ⚠️ 忽略过快点击 (间隔:' + (now - lastPredClickTime) + 'ms < ' + PRED_DEBOUNCE_MS + 'ms)');
                return;
            }
            lastPredClickTime = now;

            // 阻止事件冒泡和默认行为
            e.stopPropagation();
            e.preventDefault();

            console.log(`[飞雪监测器] 🔄 PRED 开关点击 @ ${new Date().toISOString()}`);
            console.log(`[飞雪监测器]   事件阶段: ${e.eventPhase} (1=捕获 2=目标 3=冒泡)`);
            console.log(`[飞雪监测器]   当前状态: ${predEnabled} → toggling...`);

            // 切换状态
            predEnabled = !predEnabled;

            console.log(`[飞雪监测器]   新状态: ${predEnabled}`);

            // 更新 UI
            updatePredToggleUI(toggle, knob, predEnabled);

            // 启停预测引擎（异步，不阻塞）
            togglePredictionEngine(predEnabled);

            // 保存偏好到 localStorage
            localStorage.setItem('fxm-pred-enabled', String(predEnabled));

            console.log(`[飞雪监测器] ✓ PRED 切换完成: ${predEnabled}`);
        }

        // 延迟绑定事件（防御竞态条件）(Step 2.2 + Step 2.1)
        requestAnimationFrame(() => {
            // 使用捕获阶段监听，防止冒泡到panel的关闭逻辑 (Step 2.1)
            toggle.addEventListener('click', handlePredToggleClick, { capture: true });
            console.log('[飞雪监测器] ✓ PRED Toggle 事件已绑定 (延迟模式 + 捕获阶段)');
        });

        // 初始化UI状态（根据当前 predEnabled 值）
        updatePredToggleUI(toggle, knob, predEnabled);
        console.log(`[飞雪监测器] 🎛️ PRED 开关初始化完成: ${predEnabled ? 'ON' : 'OFF'}`);

        return container;
    }

    /**
     * 更新 PRED 开关的视觉状态
     * @param {HTMLDivElement} toggle - 开关元素
     * @param {HTMLDivElement} knob - 滑块元素
     * @param {boolean} isEnabled - 是否启用
     */
    function updatePredToggleUI(toggle, knob, isEnabled) {
        if (isEnabled) {
            // ON 状态 - 绿色渐变
            toggle.style.background = 'linear-gradient(135deg, #00ff41 0%, #00cc33 100%)';
            knob.style.transform = 'translateX(20px)';
            toggle.title = 'PRED 预测已开启 - 显示工作流成功率预测';
            toggle.setAttribute('aria-checked', 'true');
        } else {
            // OFF 状态 - 灰色
            toggle.style.background = '#555555';
            knob.style.transform = 'translateX(0)';
            toggle.title = 'PRED 预测已关闭 - 点击启用';
            toggle.setAttribute('aria-checked', 'false');
        }
    }

    /**
     * 控制 PRED 预测引擎的启停
     * @param {boolean} enable - 是否启用预测引擎
     */
    async function togglePredictionEngine(enable) {
        const predCard = document.querySelector('.fxm-pred-card');
        const predContent = ((predCard != null) ? predCard.querySelector('.fxm-pred-content') : undefined);

        if (enable) {
            console.log('[飞雪监测器] 🧠 正在启动 PRED 预测引擎...');

            // 立即更新 UI 状态（同步，无等待）
            if (predCard) {
                predCard.style.opacity = '1';
            }
            if (predContent) {
                predContent.innerHTML = `
                    <div style="text-align:center;padding:15px;">
                        <div class="fxm-spinner"></div>
                        <div style="margin-top:8px;font-size:12px;opacity:0.7;">
                            正在分析工作流...
                        </div>
                    </div>
                `;
            }

            // 使用微任务确保 DOM 渲染完成后再发起网络请求（避免滞顿感）
            await new Promise(resolve => setTimeout(resolve, 0));

            try {
                // 异步获取后端数据（不阻塞 UI）
                const snapshot = await fetchFromBackend();

                if (snapshot && snapshot.prediction) {
                    displayPredictionData(snapshot.prediction);
                } else {
                    if (predContent) {
                    predContent.innerHTML = `
                        <div style="text-align:center;opacity:0.7;padding:15px;">
                            <div style="font-size:20px;margin-bottom:8px;">◆</div>  <!-- 菱形图标 -->
                            <div style="font-size:12px;font-weight:600;color:#00d4ff;">
                                预测引擎就绪
                            </div>
                            <div style="font-size:10px;margin-top:6px;color:#888;line-height:1.4;">
                                运行工作流后显示预测
                            </div>
                        </div>
                    `;
                }
                }

                console.log('[飞雪监测器] ✓ PRED 预测引擎已启动');

            } catch (error) {
                console.error('[飞雪监测器] PRED 引擎启动失败:', error);
                if (predContent) {
                    predContent.innerHTML = '<div style="color:#ff4444;text-align:center;padding:10px;font-size:11px;">引擎连接错误</div>';
                }
            }

        } else {
            console.log('[飞雪监测器] ⏹️ PRED 预测引擎已停止');

            // 显示禁用状态（Task 4: 更友好的提示样式）
            if (predCard) {
                predCard.style.opacity = '0.5';
            }
            if (predContent) {
                predContent.innerHTML = `
                    <div style="text-align:center;opacity:0.7;padding:15px;">
                        <div style="font-size:20px;margin-bottom:8px;">◆</div>  <!-- 菱形图标 -->
                        <div style="font-size:11px;font-weight:600;color:#00d4ff;">
                            PRED 就绪
                        </div>
                        <div style="font-size:9px;margin-top:6px;color:#888;line-height:1.4;">
                            加载工作流后自动激活<br/>
                            预测显存溢出风险
                        </div>
                    </div>
                `;
            }
        }
    }

    /**
     * 显示预测数据到 PRED 卡片
     * @param {Object} prediction - 预测数据对象
     */
    function displayPredictionData(prediction) {
        const predContent = document.querySelector('.fxm-pred-content');
        if (!predContent || !prediction) return;

        const successRate = prediction.success_rate || 0;
        const riskLevel = prediction.risk_level || 'unknown';

        // 风险等级颜色映射
        const riskColors = {
            'low': '#00ff41',
            'medium': '#ffaa00',
            'high': '#ff4444',
            'critical': '#ff0000',
            'unknown': '#888888'
        };

        predContent.innerHTML = `
            <div class="fxm-pred-metrics">
                <div class="fxm-pred-item">
                    <span class="fxm-pred-label">成功率</span>
                    <span class="fxm-pred-value" style="color:${riskColors[riskLevel]}">
                        ${(successRate * 100).toFixed(1)}%
                    </span>
                </div>
                <div class="fxm-pred-item">
                    <span class="fxm-pred-label">风险</span>
                    <span class="fxm-pred-value">${riskLevel.toUpperCase()}</span>
                </div>
            </div>
        `;

        // 恢复卡片透明度
        const predCard = document.querySelector('.fxm-pred-card');
        if (predCard) {
            predCard.style.opacity = '1';
        }
    }

    /**
     * 恢复用户保存的 PRED 开关偏好
     */
    function restorePredTogglePreference() {
        try {
            const saved = localStorage.getItem('fxm-pred-enabled');
            if (saved !== null) {
                predEnabled = saved === 'true';
                console.log(`[飞雪监测器] 🎛️ 已恢复 PRED 开关状态: ${predEnabled ? 'ON' : 'OFF'}`);
            }
        } catch (e) {
            // localStorage 不可用时静默失败
        }
    }

    // ============================================================
    // 7个监控指标的 SVG 图标库 (Task 2 - P1)
    // 使用内联SVG避免字体依赖，通过 currentColor 支持动态着色
    // ============================================================

    /**
     * 7个监控指标的 SVG 图标库
     * 
     * 设计原则:
     * - 所有图标使用内联SVG，避免字体/外部图片依赖
     * - 通过 currentColor 支持动态着色（除VRAM固定绿色外）
     * - 统一尺寸 14-16px，线条粗细一致
     * - 包含 drop-shadow 发光效果
     * 
     * 强制约束:
     * - VRAM 必须是绿色内存条样式（用户明确强制要求！）
     * - GPU 绝对不能用游戏手柄🎮和显示器🖥️
     */
    const FXM_ICONS = {
        /**
         * CPU - 处理器图标
         * 设计: 闪电符号，代表计算速度和处理能力
         * 风格: 线条简洁，动态感强
         */
        cpu: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
                <title>CPU</title>
              </svg>`,

        /**
         * RAM - 内存图标
         * 设计: 芯片样式，矩形+内部电路纹理
         * 风格: 技术感，区别于VRAM的绿色
         */
        ram: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <rect x="4" y="4" width="16" height="16" rx="2"/>
                <line x1="9" y1="4" x2="9" y2="20"/>
                <line x1="15" y1="4" x2="15" y2="20"/>
                <line x1="9" y1="10" x2="15" y2="10"/>
                <line x1="9" y1="14" x2="15" y2="14"/>
                <title>RAM</title>
              </svg>`,

        /**
         * GPU - 显卡图标
         * 设计: 抽象显卡形状，圆角矩形+GPU核心圆点+连接线
         * 约束: 绝对不能用游戏手柄🎮和显示器🖥️！
         * 风格: 硬件卡片形态，代表图像处理能力
         */
        gpu: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <rect x="2" y="6" width="20" height="12" rx="2"/>
                <circle cx="7" cy="12" r="2" fill="currentColor"/>
                <circle cx="17" cy="12" r="2" fill="currentColor"/>
                <path d="M10 12h4"/>
                <title>GPU</title>
              </svg>`,

        /**
         * VRAM - 显存图标（强制：绿色内存条样式！）
         * 设计: 模拟真实内存条 - 绿色PCB + 黑色芯片颗粒 + 金手指接口
         * 约束: 用户明确强制要求必须是绿色！不随状态变化！
         * 特征: 固定绿色系，带芯片颗粒细节
         */
        vram: `<svg viewBox="0 0 28 16" fill="currentColor">
                <!-- 绿色内存条主体 -->
                <rect x="2" y="2" width="24" height="12" rx="2" fill="#00cc66" opacity="0.9"/>
                <!-- 内存条边框 -->
                <rect x="2" y="2" width="24" height="12" rx="2" fill="none" stroke="currentColor" stroke-width="1" opacity="0.5"/>
                <!-- 芯片颗粒 (3个黑色小方块) -->
                <rect x="5" y="5" width="3" height="6" rx="0.5" fill="#004422" opacity="0.8"/>
                <rect x="11" y="5" width="3" height="6" rx="0.5" fill="#004422" opacity="0.8"/>
                <rect x="17" y="5" width="3" height="6" rx="0.5" fill="#004422" opacity="0.8"/>
                <!-- 金手指接口 (左侧) -->
                <rect x="0" y="5" width="2" height="6" fill="#ffd700" opacity="0.8"/>
                <title>VRAM</title>
              </svg>`,

        /**
         * TEMP - 温度图标
         * 设计: 温度计形状，底部圆形液柱
         * 风格: 简洁直观，易于识别
         */
        temp: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M14 14.76V3.5a2.5 2.5 0 0 0-5 0v11.26a4.5 4.5 0 1 0 5 0z"/>
                <circle cx="12" cy="19" r="1" fill="currentColor"/>
                <title>Temperature</title>
              </svg>`,

        /**
         * POWER - 功耗图标
         * 设计: 电源插头形状，与CPU闪电区分开
         * 风格: 代表能量消耗，有插头特征
         */
        power: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                 <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
                 <polygon points="11 18 13 20 15 18" fill="currentColor" opacity="0.5"/>
                 <title>Power</title>
               </svg>`,

        /**
         * PRED - 预测图标
         * 设计: 菱形 ◆ 形状，截图中的原始设计
         * 风格: 几何抽象，代表预测/分析能力
         */
        pred: `<svg viewBox="0 0 24 24" fill="currentColor">
                 <polygon points="12,2 22,12 12,22 2,12" opacity="0.9"/>
                 <title>PRED</title>
               </svg>`
    };

    // ============================================================
    // 图标插入辅助函数 (Task 2 - P1)
    // ============================================================

    /**
     * 为胶囊添加 SVG 图标
     * 
     * 功能:
     * - 从 FXM_ICONS 库获取对应指标的 SVG 代码
     * - 插入到胶囊的 .fxm-capsule__icon 容器中
     * - 设置统一的尺寸和发光效果
     * - 特殊处理 VRAM 图标（固定绿色，不随状态变化）
     * 
     * @param {HTMLElement} capsule - 胶囊 DOM 元素
     * @param {string} metricType - 指标类型 (cpu/ram/gpu/vram/temp/power/pred)
     */
    function addCapsuleIcon(capsule, metricType) {
        const iconContainer = capsule.querySelector('.fxm-capsule__icon');
        if (!iconContainer) {
            console.warn(`[飞雪监测器] ⚠️ 找不到图标容器 .fxm-capsule__icon (metric: ${metricType})`);
            return;
        }

        const svgCode = FXM_ICONS[metricType];
        if (!svgCode) {
            console.warn(`[飞雪监测器] ⚠️ 未找到图标定义: ${metricType}`);
            return;
        }

        // 插入 SVG 代码
        iconContainer.innerHTML = svgCode;

        // 设置图标容器基础样式
        Object.assign(iconContainer.style, {
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: '16px',
            height: '16px',
            flexShrink: '0',
            marginRight: '4px'   /* 从6px减小到4px，节省空间 */
        });

        // 显存图标特殊处理：始终保持绿色系（用户强制要求！）
        if (metricType === 'vram') {
            iconContainer.style.color = '#00ff88';
            iconContainer.style.filter = 'drop-shadow(0 0 4px rgba(0, 255, 136, 0.5))';
        } else {
            // 其他图标使用 currentColor（由父元素/状态控制）
            iconContainer.style.color = 'inherit';
            iconContainer.style.filter = 'drop-shadow(0 0 3px currentColor)';
        }
    }

    /**
     * 指标ID到图标类型的映射表
     * 用于将 metrics 数组中的 id 映射到 FXM_ICONS 的 key
     */
    const METRIC_ICON_MAP = {
        'prediction': 'pred',
        'cpu': 'cpu',
        'ram': 'ram',
        'gpu': 'gpu',
        'vram': 'vram',
        'rsv': 'vram',  // 预留显存复用 vram 图标
        'power': 'power'
    };

    // ============================================================
    // 性能等级检测
    // ============================================================
    function detectPerformanceLevel() {
        const canvas = document.createElement('canvas');
        const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');

        if (!gl) return 'low';  // 无WebGL支持

        const debugInfo = gl.getExtension('WEBGL_debug_renderer_info');
        const renderer = debugInfo ? gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL) : '';

        // 检测是否是集成显卡或低端显卡
        if (renderer.includes('Intel') || renderer.includes('HD Graphics')) return 'low';
        if (renderer.includes('Radeon') && !renderer.includes('RX 6000') && !renderer.includes('RX 7000')) return 'mid';

        return 'high';  // 默认高端
    }

    const perfLevel = detectPerformanceLevel();
    console.log(`[飞雪监测器] 🖥️ 性能等级: ${perfLevel} (${perfLevel === 'low' ? '简化模式' : '完整模式'})`);

    // ============================================================
    // 方案C: backdrop-filter 兼容性检测 (Scheme C Compatibility)
    // ============================================================
    
    /**
     * 检测浏览器是否支持 backdrop-filter (毛玻璃效果)
     * 
     * 实现策略:
     * 1. CSS.supports() API 检测标准属性支持
     * 2. 创建临时DOM元素测试实际渲染能力
     * 3. 双重验证确保准确性
     * 
     * @returns {Object} 包含支持状态和详细信息的对象
     *   - supported {boolean}: 是否完全支持
     *   - webkitSupported {boolean}: 是否支持webkit前缀
     *   - method {string}: 检测方法 ('css-supports' | 'element-test' | 'both')
     *   - browserInfo {string}: 浏览器信息
     */
    function checkBackdropFilterSupport() {
        const result = {
            supported: false,
            webkitSupported: false,
            method: 'unknown',
            browserInfo: ''
        };

        // 方法1: 使用 CSS.supports() API (现代浏览器推荐方法)
        const cssSupportsStandard = CSS.supports('backdrop-filter', 'blur(1px)');
        const cssSupportsWebkit = CSS.supports('-webkit-backdrop-filter', 'blur(1px)');

        console.log(`[方案C] CSS.supports() 检测结果:`);
        console.log(`  - 标准backdrop-filter: ${cssSupportsStandard}`);
        console.log(`  - -webkit-backdrop-filter: ${cssSupportsWebkit}`);

        // 方法2: 创建临时元素进行实际渲染测试 (更准确)
        const testEl = document.createElement('div');
        testEl.style.cssText = 'position: fixed; left: -9999px; top: -9999px; visibility: hidden;';
        testEl.style.backdropFilter = 'blur(1px)';
        testEl.style.webkitBackdropFilter = 'blur(1px)';
        
        document.body.appendChild(testEl);
        
        // 获取计算样式验证属性是否生效
        const computedStyle = window.getComputedStyle(testEl);
        const standardBackdropFilter = computedStyle.backdropFilter;
        const webkitBackdropFilter = computedStyle.webkitBackdropFilter;
        
        document.body.removeChild(testEl);

        console.log(`[方案C] 元素测试结果:`);
        console.log(`  - 计算后标准值: "${standardBackdropFilter}"`);
        console.log(`  - 计算后webkit值: "${webkitBackdropFilter}"`);

        // 综合判断支持情况
        result.webkitSupported = cssSupportsWebkit || webkitBackdropFilter !== 'none';
        result.supported = cssSupportsStandard || standardBackdropFilter !== 'none' || result.webkitSupported;

        // 确定检测方法
        if (cssSupportsStandard && standardBackdropFilter !== 'none') {
            result.method = 'both';
        } else if (cssSupportsStandard) {
            result.method = 'css-supports';
        } else if (standardBackdropFilter !== 'none') {
            result.method = 'element-test';
        } else if (result.webkitSupported) {
            result.method = 'webkit-only';
        } else {
            result.method = 'not-supported';
        }

        // 获取浏览器信息
        const ua = navigator.userAgent;
        let browserName = 'Unknown';
        if (ua.includes('Firefox')) browserName = 'Firefox';
        else if (ua.includes('Chrome')) browserName = 'Chrome';
        else if (ua.includes('Safari')) browserName = 'Safari';
        else if (ua.includes('Edge')) browserName = 'Edge';
        else if (ua.includes('MSIE') || ua.includes('Trident')) browserName = 'IE';
        
        var _matchResult = ua.match(/(Chrome|Firefox|Safari|Edge)\/[\d.]+/);
        result.browserInfo = `${browserName} (${(_matchResult != null ? _matchResult[0] : undefined) || 'N/A'})`;

        // 输出详细日志
        console.log(`[方案C] ✅ 兼容性检测完成:`);
        console.log(`  浏览器: ${result.browserInfo}`);
        console.log(`  标准支持: ${result.supported ? '✅' : '❌'}`);
        console.log(`  WebKit支持: ${result.webkitSupported ? '✅' : '❌'}`);
        console.log(`  检测方法: ${result.method}`);

        return result;
    }

    /**
     * 应用方案C兼容性降级
     * 当检测到不支持backdrop-filter时，自动添加fallback类
     * 
     * @param {Object} supportResult - checkBackdropFilterSupport()的返回值
     */
    function applySchemeCFallback(supportResult) {
        if (!supportResult.supported) {
            console.warn(`[方案C] ⚠️ 浏览器不支持backdrop-filter，应用降级方案`);
            
            // 给所有scheme-c元素添加fallback类
            const schemeCCapsules = document.querySelectorAll('.fxm-capsule.scheme-c');
            schemeCCapsules.forEach(el => {
                el.classList.add('no-glass');
                console.log(`[方案C]   已为元素添加 .no-glass 类:`, ((el.dataset != null) ? el.dataset.metric : undefined) || 'unknown');
            });

            if (schemeCCapsules.length === 0) {
                console.log(`[方案C]   当前没有scheme-c元素，降级CSS将自动生效`);
            }
        } else {
            console.log(`[方案C] ✓ 浏览器完全支持backdrop-filter，使用完整玻璃态效果`);
        }
    }

    /**
     * 方案C性能优化: 动态控制will-change属性
     * 
     * 设计原则:
     * - will-change仅在hover时应用，避免内存泄漏
     * - mouseenter时激活GPU加速层
     * - mouseleave时释放GPU资源
     * 
     * @param {boolean} enable - 是否启用优化 (默认true)
     */
    function optimizeSchemeCPerformance(enable = true) {
        if (!enable) {
            console.log('[方案C] 性能优化已禁用');
            return;
        }

        const schemeCCapsules = document.querySelectorAll('.fxm-capsule.scheme-c');
        
        if (schemeCCapsules.length === 0) {
            console.log('[方案C] 未找到scheme-c元素，跳过性能优化初始化');
            return;
        }

        console.log(`[方案C] 正在为${schemeCCapsules.length}个胶囊初始化will-change优化...`);

        schemeCCapsules.forEach(cap => {
            // Hover时激活GPU加速
            cap.addEventListener('mouseenter', () => {
                cap.style.willChange = 'transform, backdrop-filter, box-shadow';
            }, { passive: true });  /* 被动事件监听，提升滚动性能 */

            // Leave时释放GPU资源
            cap.addEventListener('mouseleave', () => {
                cap.style.willChange = 'auto';
            }, { passive: true });
        });

        console.log('[方案C] ✓ will-change动态优化已启用 (hover时激活/离开时释放)');
    }

    // 执行兼容性检测 (延迟到DOM就绪后)
    let schemeCSupportCache = null;  /* 缓存检测结果避免重复检测 */

    /**
     * 初始化方案C兼容性 (在DOM就绪后调用)
     * 包括:
     * 1. 检测backdrop-filter支持
     * 2. 应用必要的降级
     * 3. 启用性能优化
     */
    function initSchemeCCompatibility() {
        if (schemeCSupportCache) {
            console.log('[方案C] 使用缓存的兼容性检测结果');
            applySchemeCFallback(schemeCSupportCache);
            optimizeSchemeCPerformance(performanceMode);
            return schemeCSupportCache;
        }

        console.log('[方案C] 🔍 开始兼容性检测...');
        
        // 执行检测
        schemeCSupportCache = checkBackdropFilterSupport();
        
        // 应用降级（如果需要）
        applySchemeCFallback(schemeCSupportCache);
        
        // 启用性能优化（仅在性能模式下）
        optimizeSchemeCPerformance(performanceMode);

        // 将检测结果暴露到全局供调试使用
        window.__schemeCSupport = schemeCSupportCache;

        return schemeCSupportCache;
    }

    // 根据性能级别生成毛玻璃样式
    function getGlassStyle(intensity) {
        if (perfLevel === 'low') {
            return `background: rgba(10, 14, 23, ${intensity === 'high' ? 0.95 : 0.92});`;
        }
        const blurValue = intensity === 'high' ? '15px' : '20px';
        return `background: rgba(10, 14, 23, ${intensity === 'high' ? 0.85 : 0.85}); backdrop-filter: blur(${blurValue}); -webkit-backdrop-filter: blur(${blurValue});`;
    }

    // ============================================================
    // 统一数据源模式 - 解决胶囊/面板数据一致性问题（Task 7）
    // ============================================================
    
    /**
     * 统一系统数据缓存
     * @type {Object|null}
     */
    let cachedSystemData = null;
    
    /**
     * 上次统一数据更新时间戳
     * @type {number}
     */
    let lastUnifiedDataTime = 0;
    
    /**
     * 统一数据缓存有效期（毫秒）
     * @constant {number}
     */
    const UNIFIED_DATA_CACHE_TTL = 1500;  // 1.5秒内所有UI组件共享同一份数据
    
    /**
     * 统一数据源函数 - 确保胶囊和面板显示完全相同的数据
     * 
     * **设计原则**:
     * - 所有UI组件（胶囊、面板）必须通过此函数获取数据
     * - 在缓存有效期内（1.5s），多次调用返回同一对象引用
     * - 缓存过期后自动从后端获取新数据
     * - 添加详细日志用于调试一致性
     * 
     * @async
     * @returns {Promise<Object>} 统一的系统数据对象
     */
    async function getUnifiedSystemData() {
        const now = Date.now();
        const timeSinceLastUpdate = now - lastUnifiedDataTime;
        
        // 缓存命中检查
        if (cachedSystemData && timeSinceLastUpdate < UNIFIED_DATA_CACHE_TTL) {
            console.log(`[飞雪监测器] 📦 使用缓存数据 (${(timeSinceLastUpdate).toFixed(0)}ms前获取, 剩余${(UNIFIED_DATA_CACHE_TTL - timeSinceLastUpdate).toFixed(0)}ms)`);
            
            // 标记此数据的消费者
            if (!cachedSystemData._consumers) {
                cachedSystemData._consumers = [];
            }
            
            return cachedSystemData;
        }
        
        // 缓存过期或无缓存 - 从后端获取新数据
        console.log('[飞雪监测器] 🔄 从后端获取新数据 (缓存已过期或首次加载)');
        
        try {
            // 调用原有的数据采集函数
            cachedSystemData = await collectSystemData();
            lastUnifiedDataTime = now;
            
            // 标记数据元信息
            cachedSystemData._unifiedTimestamp = now;
            cachedSystemData._consumers = ['pending'];  // 将被替换为实际消费者
            
            // 详细日志记录
            console.log('[飞雪监测器] 📊 数据同步更新:', {
                timestamp: now,
                cpu: (cachedSystemData.cpu != null ? cachedSystemData.cpu.usage : undefined),
                gpu: (cachedSystemData.gpu != null ? cachedSystemData.gpu.usage : undefined),
                ram: (cachedSystemData.ram != null ? cachedSystemData.ram.percent : undefined),
                _source: cachedSystemData._source || cachedSystemData.data_source,
                cacheTTL: `${UNIFIED_DATA_CACHE_TTL}ms`,
            });
            
            return cachedSystemData;
            
        } catch (error) {
            console.error('[飞雪监测器] ❌ 统一数据获取失败:', error.message);
            
            // 返回错误状态数据
            return {
                timestamp: Date.now(),
                cpu: { usage: null, cores: null, freq_mhz: null, per_core_usage: null },
                ram: { total: null, used: null, percent: null, free: null },
                gpu: { usage: null, vram_used: null, vram_total: null, temperature: null,
                       device_name: null, device_id: null, power_usage_w: null, clock_speed_mhz: null },
                prediction: { success_rate: null, risk_level: 'ERROR', confidence: null },
                power: { draw_w: null, limit_w: null, percent: null },
                reserved_mb: null,
                data_source: 'error',
                data_source_desc: `统一数据源错误: ${error.message}`,
                _backend_available: false,
                _unifiedTimestamp: Date.now(),
            };
        }
    }
    
    /**
     * 一致性检查定时器ID
     * @type {number|null}
     */
    let consistencyCheckInterval = null;
    
    /**
     * 启动定时一致性检查（每10秒执行一次）
     * 
     * 用于验证胶囊和面板的数值是否一致，
     * 如果发现不一致会在控制台输出警告。
     */
    function startConsistencyCheck() {
        if (consistencyCheckInterval) {
            clearInterval(consistencyCheckInterval);  // 防止重复启动
        }
        
        consistencyCheckInterval = setInterval(() => {
            try {
                // 获取胶囊的数值
                const capsuleCPU = ((_qs = document.querySelector('[data-metric="cpu"] .fxm-value')) != null ? _qs.textContent : undefined);
                const capsuleRAM = ((_qs = document.querySelector('[data-metric="ram"] .fxm-value')) != null ? _qs.textContent : undefined);
                const capsuleGPU = ((_qs = document.querySelector('[data-metric="gpu"] .fxm-value')) != null ? _qs.textContent : undefined);
                
                // 获取面板的数值
                const panelCPU = ((_qs2 = document.querySelector('.fxm-cpu-value')) != null ? _qs2.textContent : undefined);
                const panelRAM = ((_qs2 = document.querySelector('.fxm-ram-value')) != null ? _qs2.textContent : undefined);
                const panelGPU = ((_qs2 = document.querySelector('.fxm-gpu-value')) != null ? _qs2.textContent : undefined);
                
                // 比较并报告差异
                let hasInconsistency = false;
                const differences = [];
                
                if (capsuleCPU && panelCPU && capsuleCPU !== panelCPU && 
                    capsuleCPU !== '--' && panelCPU !== '--' && panelCPU !== 'N/A') {
                    hasInconsistency = true;
                    differences.push(`CPU: 胶囊=${capsuleCPU} vs 面板=${panelCPU}`);
                }
                
                if (capsuleRAM && panelRAM && capsuleRAM !== panelRAM &&
                    capsuleRAM !== '--' && panelRAM !== '--' && panelRAM !== 'N/A') {
                    hasInconsistency = true;
                    differences.push(`RAM: 胶囊=${capsuleRAM} vs 面板=${panelRAM}`);
                }
                
                if (capsuleGPU && panelGPU && capsuleGPU !== panelGPU &&
                    capsuleGPU !== '--' && panelGPU !== '--' && panelGPU !== 'N/A') {
                    hasInconsistency = true;
                    differences.push(`GPU: 胶囊=${capsuleGPU} vs 面板=${panelGPU}`);
                }
                
                if (hasInconsistency) {
                    console.warn('[飞雪监测器] ⚠️ 数据一致性警告:', {
                        timestamp: new Date().toLocaleTimeString(),
                        differences: differences,
                        suggestion: '如果持续出现此警告，请检查 updatePanelData() 是否使用了统一数据源'
                    });
                } else if (panelVisible) {
                    // 仅在面板可见时输出成功日志（避免刷屏）
                    console.log('[飞雪监测器] ✓ 一致性检查通过 - 胶囊与面板数据同步');
                }
                
            } catch (e) {
                // 静默处理检查过程中的错误
                console.debug('[飞雪监测器] 一致性检查跳过:', e.message);
            }
        }, 10000);  // 每10秒检查一次
        
        console.log('[飞雪监测器] 🔍 已启动一致性检查定时器 (间隔: 10s)');
    }
    
    /**
     * 停止一致性检查
     */
    function stopConsistencyCheck() {
        if (consistencyCheckInterval) {
            clearInterval(consistencyCheckInterval);
            consistencyCheckInterval = null;
        }
    }

    // ============================================================
    // 定时器管理
    // ============================================================
    let dataUpdateInterval = null;

    function startDataCollection() {
        stopDataCollection();  // 先清理已有的（防止重复）

        dataUpdateInterval = setInterval(async () => {
            // ✅ 使用统一数据源函数 - 确保只获取一次数据
            const unifiedData = await getUnifiedSystemData();
            
            // 更新胶囊（传入同一份统一数据）
            updateCapsules(unifiedData);

            // 更新面板（如果可见，也使用同一份统一数据）
            if (panelVisible) {
                updatePanelData(unifiedData);  // ← 修改：传入参数而非重新获取
            }
        }, CONFIG.updateInterval);
        
        // 启动一致性检查
        startConsistencyCheck();
    }

    function stopDataCollection() {
        if (dataUpdateInterval) {
            clearInterval(dataUpdateInterval);
            dataUpdateInterval = null;
        }
        
        // 同时停止一致性检查
        stopConsistencyCheck();
    }

    // ============================================================
    // GPU 数据采集 - 多策略实现
    // ============================================================
    
    /**
     * 策略1: WebGPU API (实验性，Chrome支持)
     */
    async function getWebGPUInfo() {
        if (!navigator.gpu) {
            console.log('[飞雪监测器] 🎮 WebGPU API 不可用');
            return null;
        }

        try {
            const adapter = await navigator.gpu.requestAdapter();
            if (!adapter) {
                console.log('[飞雪监测器] 🎮 无法获取GPU适配器');
                return null;
            }

            const info = await adapter.requestAdapterInfo();
            console.log('[飞雪监测器] 🎮 WebGPU 信息:', info);

            return {
                gpu_name: `${info.vendor || 'Unknown'} ${info.architecture || ''}`.trim(),
                driver: info.description || '',
                data_source: 'webgpu'
            };
        } catch (e) {
            console.warn('[飞雪监测器] ⚠️ WebGPU API 获取失败:', e.message);
            return null;
        }
    }

    /**
     * 策略2: 从 ComfyUI 内部对象获取信息
     */
    function getComfyUIGPUInfo() {
        const info = { data_source: null };

        // 尝试从 ComfyUI app 对象获取
        if (typeof app !== 'undefined') {
            console.log('[飞雪监测器] 📦 检测到 ComfyUI app 对象');
            
            if (app.nodeOutputs) {
                info.data_source = 'comfyui-api';
                info.has_execution_data = true;
            }
            
            // 尝试获取图形后端信息
            if (app.canvas && app.canvas.getContext('webgl2')) {
                const gl = app.canvas.getContext('webgl2');
                const debugInfo = gl.getExtension('WEBGL_debug_renderer_info');
                if (debugInfo) {
                    const renderer = gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL);
                    info.webgl_renderer = renderer;
                    console.log('[飞雪监测器] 📦 WebGL 渲染器:', renderer);
                    
                    // 解析 GPU 名称和显存信息
                    if (renderer.includes('Radeon RX 6800')) {
                        info.detected_gpu = 'AMD Radeon RX 6800';
                        info.detected_vram_gb = 16;
                        info.data_source = info.data_source || 'comfyui-webgl';
                    }
                }
            }
        }

        return info.data_source ? info : null;
    }

    /**
     * 策略3: 基于 WebGL 的 GPU 检测
     */
    function getWebGLGPUInfo() {
        const canvas = document.createElement('canvas');
        const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');

        if (!gl) return null;

        const debugInfo = gl.getExtension('WEBGL_debug_renderer_info');
        if (!debugInfo) return null;

        const renderer = gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL);
        const vendor = gl.getParameter(debugInfo.UNMASKED_VENDOR_WEBGL);

        console.log(`[飞雪监测器] 🔍 WebGL GPU: ${vendor} - ${renderer}`);

        // 已知 GPU 数据库
        const gpuDatabase = {
            'Radeon RX 6800': {
                name: 'AMD Radeon RX 6800',
                vram_total_gb: 16,
                tdp_w: 250,
                base_clock_mhz: 1700,
                memory_type: 'GDDR6'
            },
            'Radeon RX 6900 XT': {
                name: 'AMD Radeon RX 6900 XT',
                vram_total_gb: 16,
                tdp_w: 300,
                base_clock_mhz: 1825,
                memory_type: 'GDDR6'
            },
            'GeForce RTX 3080': {
                name: 'NVIDIA GeForce RTX 3080',
                vram_total_gb: 10,
                tdp_w: 320,
                base_clock_mhz: 1440,
                memory_type: 'GDDR6X'
            },
            'GeForce RTX 3090': {
                name: 'NVIDIA GeForce RTX 3090',
                vram_total_gb: 24,
                tdp_w: 350,
                base_clock_mhz: 1395,
                memory_type: 'GDDR6X'
            }
        };

        // 匹配已知的 GPU
        for (const [key, gpu] of Object.entries(gpuDatabase)) {
            if (renderer.includes(key)) {
                return {
                    ...gpu,
                    webgl_renderer: renderer,
                    webgl_vendor: vendor,
                    data_source: 'webgl-database'
                };
            }
        }

        // 如果没有匹配到，返回基本的 WebGL 信息
        return {
            name: renderer,
            webgl_renderer: renderer,
            webgl_vendor: vendor,
            vram_total_gb: null, // 未知
            tdp_w: null,
            data_source: 'webgl-generic'
        };
    }

    // ============================================================
    // ⚠️ 已废弃的函数 - 不再使用 Math.random() 生成假数据
    // ============================================================
    //
    // 原有的 estimateGPUData() 和 collectGPUData() 函数已完全移除。
    // 它们使用 Math.random() 生成随机数据，违反"数据真实性 > 视觉炫酷"原则。
    //
    // 当前所有 GPU 数据均通过 collectSystemData() -> fetchFromBackend() 从后端 API 获取。
    // 如果后端不可用，所有数值字段返回 null，UI 显示 '--' 占位符。
    //
    // 数据来源优先级：
    // 1. 后端 API (真实数据) ✅
    // 2. null (显示 '--') ✅
    // 3. ~~Math.random()~~ ❌ 已禁止
    //

    // ============================================================
    // 数据采集 - 从后端 API 获取真实数据（Task 2 实现）
    // ============================================================
    
    /**
     * 缓存配置
     * @constant {Object}
     */
    const CACHE_CONFIG = {
        ttl: 1500,  // 缓存有效期 1.5 秒（避免高频请求）
        maxRetries: 3,  // 最大重试次数
        timeout: 3000,  // 请求超时时间 (ms)
    };
    
    /** @type {Object|null} 缓存的后端数据 */
    let cachedData = null;
    /** @type {number} 上次成功获取数据的时间戳 */
    let lastFetchTime = 0;
    /** @type {number} 连续失败计数器 */
    let consecutiveFailures = 0;
    /** @type {boolean} 后端可用性标志 */
    let backendAvailable = null;  // null=未知, true=可用, false=不可用
    
    /**
     * 从后端 API 获取监控数据（带缓存机制）
     * 
     * 实现了：
     * - 时间缓存（避免 1.5s 内重复请求）
     * - 超时保护（3秒超时）
     * - 错误重试（最多3次）
     * - 降级处理（后端不可用时返回占位符）
     * 
     * @async
     * @returns {Promise<Object|null>} 后端数据对象，或 null（如果不可用）
     */
    async function fetchFromBackend() {
        const now = Date.now();
        
        // 缓存命中检查：如果缓存有效，直接返回
        if (cachedData && (now - lastFetchTime) < CACHE_CONFIG.ttl) {
            return cachedData;
        }
        
        try {
            // 创建 AbortController 用于超时控制
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), CACHE_CONFIG.timeout);
            
            // 发起 HTTP GET 请求
            const response = await fetch('/feixue_monitor/snapshot', {
                method: 'GET',
                signal: controller.signal,
                headers: {
                    'Accept': 'application/json',
                }
            });
            
            // 清除超时定时器
            clearTimeout(timeoutId);
            
            // 检查 HTTP 状态码
            if (!response.ok) {
                console.warn(`[飞雪监测器] 后端返回错误状态码: ${response.status}`);
                
                // 特殊处理 503 Service Unavailable（监控未运行）
                if (response.status === 503) {
                    backendAvailable = false;
                    return null;
                }
                
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            
            // 解析 JSON 响应
            const data = await response.json();
            
            // 验证数据有效性
            if (!data || data.error) {
                console.warn('[飞雪监测器] 后端返回无效数据:', data);
                throw new Error(data.error || 'Invalid data format');
            }
            
            // 验证必要字段存在
            if (!data.cpu && !data.ram) {
                console.warn('[飞雪监测器] 后端数据缺少 CPU/RAM 字段');
                throw new Error('Missing required fields');
            }
            
            // 更新缓存
            cachedData = data;
            lastFetchTime = now;
            consecutiveFailures = 0;  // 重置失败计数器
            backendAvailable = true;
            
            // 标记数据来源为真实后端
            data._source = 'backend-api';
            
            // 日志记录（首次连接时详细记录）
            if (consecutiveFailures === 0 || backendAvailable === true) {
                console.log('[飞雪监测器] ✓ 收到真实后端数据:', {
                    cpu: ((data.cpu != null && data.cpu.utilization != null) ? data.cpu.utilization.toFixed(1) : undefined) + '%',
                    gpu: ((data.gpu != null && data.gpu.utilization != null) ? data.gpu.utilization.toFixed(1) : undefined) + '%',
                    ram: ((data.ram != null && data.ram.percent != null) ? data.ram.percent.toFixed(1) : undefined) + '%',
                    source: data.data_source,
                });
            }
            
            return data;
            
        } catch (error) {
            // 错误处理
            consecutiveFailures++;
            
            // 区分不同类型的错误
            if (error.name === 'AbortError') {
                console.warn(`[飞雪监测器] 请求超时 (${CACHE_CONFIG.timeout}ms)`);
            } else if (error.message.includes('Failed to fetch')) {
                console.warn('[飞雪监测器] 网络错误: 无法连接到后端服务');
                backendAvailable = false;
            } else {
                console.warn(`[飞雪监测器] 数据获取失败 (${consecutiveFailures}/${CACHE_CONFIG.maxRetries}):`, error.message);
            }
            
            // 如果超过最大重试次数，标记后端不可用
            if (consecutiveFailures >= CACHE_CONFIG.maxRetries) {
                backendAvailable = false;
                console.warn('[飞雪监测器] 后端不可用，将显示占位符数据');
            }
            
            return null;
        }
    }
    
    /**
     * 主数据采集函数 - 统一的数据接口
     * 
     * 优先从后端 API 获取真实数据，失败时显示占位符。
     * 
     * **重要变更（Task 2）**:
     * - 不再使用 Math.random() 生成假数据
     * - 后端不可用时所有指标显示 '--' 或 null
     * - 添加 _source 标识数据来源
     * 
     * @async
     * @returns {Promise<Object>} 标准化的系统数据对象
     */
    async function collectSystemData() {
        try {
            // 尝试从后端获取真实数据
            const realData = await fetchFromBackend();
            
            if (realData) {
                // ✅ 使用真实后端数据
                console.log('[飞雪监测器] ✓ 使用真实后端数据');
                
                return {
                    timestamp: realData.timestamp || Date.now(),
                    
                    // CPU 数据
                    cpu: {
                        usage: (realData.cpu != null ? realData.cpu.utilization : null),
                        cores: (realData.cpu != null ? realData.cpu.cores : null),
                        freq_mhz: (realData.cpu != null ? realData.cpu.freq_mhz : null),
                        per_core_usage: (realData.cpu != null ? realData.cpu.per_core_usage : null),
                    },
                    
                    // RAM 数据（转换为 GB）
                    ram: {
                        total: (realData.ram != null ? realData.ram.total_gb : null),
                        used: (realData.ram != null ? realData.ram.used_gb : null),
                        percent: (realData.ram != null ? realData.ram.percent : null),
                        free: (realData.ram != null ? realData.ram.free_gb : null),
                    },
                    
                    // GPU 数据
                    gpu: {
                        usage: (realData.gpu != null ? realData.gpu.utilization : null),
                        vram_used: (realData.gpu != null ? realData.gpu.vram_used_gb : null),
                        vram_total: (realData.gpu != null ? realData.gpu.vram_total_gb : null),
                        temperature: (realData.gpu != null ? realData.gpu.temperature : null),
                        device_name: (realData.gpu != null ? realData.gpu.device_name : null),
                        device_id: (realData.gpu != null ? realData.gpu.device_id : null),
                        power_usage_w: (realData.gpu != null ? realData.gpu.power_usage_w : null),
                        clock_speed_mhz: (realData.gpu != null ? realData.gpu.clock_speed_mhz : null),
                    },
                    
                    // 预测数据（Task 5 实现，当前为 null）
                    prediction: realData.prediction ? {
                        success_rate: (realData.prediction.success_rate != null ? realData.prediction.success_rate : 0),
                        risk_level: (realData.prediction.risk_level != null ? realData.prediction.risk_level : 'LOW'),
                        confidence: (realData.prediction.confidence != null ? realData.prediction.confidence : 0),
                    } : null,
                    
                    // 功耗数据
                    power: realData.power ? {
                        draw_w: (realData.power.current_power_w != null ? realData.power.current_power_w : null),
                        limit_w: (realData.power.limit_power_w != null ? realData.power.limit_power_w : null),
                        percent: (realData.power.power_percent != null ? realData.power.power_percent : null),
                    } : null,
                    
                    // 预留显存（PyTorch 缓存池，暂无数据来源）
                    reserved_mb: null,
                    
                    // 元数据
                    data_source: 'backend-api',
                    data_source_desc: `后端API (${realData.data_source || 'unknown'})`,
                    _backend_available: true,
                };
            } else {
                // ❌ 后端不可用 - 显示占位符（不是假数据！）
                console.warn('[飞雪监测器] ⚠️ 后端不可用，显示占位符 "--"');
                
                return {
                    timestamp: Date.now(),
                    
                    cpu: {
                        usage: null,  // 显示 '--'
                        cores: navigator.hardwareConcurrency || null,
                        freq_mhz: null,
                        per_core_usage: null,
                    },
                    
                    ram: {
                        total: null,  // 显示 '--'
                        used: null,   // 显示 '--'
                        percent: null,  // 显示 '--'
                        free: null,
                    },
                    
                    gpu: {
                        usage: null,       // 显示 '--'
                        vram_used: null,   // 显示 '--'
                        vram_total: null,  // 显示 '--'
                        temperature: null,
                        device_name: null,
                        device_id: null,
                        power_usage_w: null,
                        clock_speed_mhz: null,
                    },
                    
                    prediction: {
                        success_rate: null,  // 显示 '--'
                        risk_level: 'UNKNOWN',
                        confidence: null,
                    },
                    
                    power: {
                        draw_w: null,   // 显示 '--'
                        limit_w: null,
                        percent: null,
                    },
                    
                    reserved_mb: null,  // 显示 '--'
                    
                    // 明确标记数据来源
                    data_source: 'unavailable',
                    data_source_desc: '后端服务不可用',
                    _backend_available: false,
                };
            }
            
        } catch (e) {
            // 极端情况下的兜底处理
            console.error('[飞雪监测器] ❌ 数据采集异常:', e.message);
            
            return {
                timestamp: Date.now(),
                cpu: { usage: null, cores: null, freq_mhz: null, per_core_usage: null },
                ram: { total: null, used: null, percent: null, free: null },
                gpu: { usage: null, vram_used: null, vram_total: null, temperature: null, 
                       device_name: null, device_id: null, power_usage_w: null, clock_speed_mhz: null },
                prediction: { success_rate: null, risk_level: 'ERROR', confidence: null },
                power: { draw_w: null, limit_w: null, percent: null },
                reserved_mb: null,
                data_source: 'error',
                data_source_desc: `采集异常: ${e.message}`,
                _backend_available: false,
            };
        }
    }

    // ============================================================
    // UI创建 - 毛玻璃顶部菜单栏 (Task 3: 胶囊底盘增强版)
    // ============================================================
    function createTopMenuBar() {
        const bar = document.createElement('div');
        bar.id = 'fxm-top-menu-bar';
        bar.style.cssText = `
            position: fixed;
            top: ${CONFIG.position.top};
            right: ${CONFIG.position.right};
            display: flex;
            align-items: center;
            gap: 8px;
            z-index: 9999;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            animation: fxm-slideIn 0.5s ease-out;
        `;

        // ===== Task 3: 创建胶囊底盘容器 (.fxm-capsule-tray) =====
        // 深色凹陷背景，衬托胶囊的3D凸起感
        const tray = document.createElement('div');
        tray.className = 'fxm-capsule-tray';
        tray.id = 'fxm-capsule-tray';
        console.log('[飞雪监测器] 🎨 创建胶囊底盘容器 (.fxm-capsule-tray)');

        const metrics = [
            { id: 'prediction', label: '预测', unit: '%', defaultVal: '--' },
            { id: 'cpu', label: '处理器', unit: '%', defaultVal: '--' },
            { id: 'ram', label: '内存', unit: 'GB', defaultVal: '--' },
            { id: 'gpu', label: '显卡', unit: '%', defaultVal: '--' },
            { id: 'vram', label: '显存', unit: 'GB', defaultVal: '--' },
            { id: 'rsv', label: '预留', unit: 'MB', defaultVal: '--' },
            { id: 'power', label: '功耗', unit: 'W', defaultVal: '--' }
        ];

        metrics.forEach(metric => {
            const capsule = document.createElement('div');
            // 使用当前配置的方案（默认scheme-a，可切换到scheme-b/scheme-c）
            capsule.className = 'fxm-capsule ' + CONFIG.currentScheme;
            capsule.dataset.metric = metric.id;

            // 根据方案应用不同的基础样式
            if (CONFIG.currentScheme === 'scheme-c') {
                // ============================================================
                // 方案C: Glassmorphism Refined (精致玻璃态)
                // 
                // 核心视觉特征 (已由CSS类 .fxm-capsule.scheme-c 完整定义):
                // - 高度: 36px (大圆角胶囊)
                // - 圆角: 24px (--scheme-c-capsule-radius)
                // - 背景: rgba(255,255,255,0.05) + backdrop-filter: blur(20px)
                // - 边框: 1px solid rgba(255,255,255,0.15) 半透明白色
                // - 阴影: 内高光 + 物理感投影
                //
                // 此处仅保留必要的布局属性，不覆盖CSS视觉样式！
                // ============================================================
                capsule.style.cssText = `
                    display: inline-flex;
                    align-items: center;
                    gap: var(--fxm-capsule-gap, 6px);
                    cursor: default;
                    user-select: none;
                    white-space: nowrap;
                    overflow: hidden;
                    position: relative;
                    
                    /* 方案C特殊: 确保内部文字使用纯白色最高对比度 */
                    color: #FFFFFF;
                `;
                
                console.log(`[方案C] 创建玻璃态胶囊: ${metric.label} (36px高度, 24px圆角, backdrop-filter)`);

            } else if (CONFIG.currentScheme === 'scheme-b') {
                // 方案B: Cyberpunk Tech - 切角几何造型，霓虹风格
                // 核心视觉样式已由CSS类 .fxm-capsule.scheme-b 控制
                // 此处仅保留必要的布局属性（CSS已定义clip-path、背景、边框等）
                capsule.style.cssText = `
                    display: inline-flex;
                    align-items: center;
                    gap: calc(var(--fxm-capsule-gap, 6px) + 2px);
                    cursor: default;
                    user-select: none;
                    white-space: nowrap;
                    overflow: hidden;
                    position: relative;
                `;
            } else {
                // 方案A: Minimalist Pro - 极简主义专业版 (32px enhanced / 26px standard, 9999px圆角)
                // 注意: 核心视觉样式已由CSS类 .fxm-capsule.scheme-a 控制
                // 此处仅保留必要的布局属性
                capsule.style.cssText = `
                    display: flex;
                    align-items: center;
                    gap: 6px;
                    cursor: pointer;
                    transition: all 0.15s cubic-bezier(0.16, 1, 0.3, 1);
                    white-space: nowrap;
                    user-select: none;
                    position: relative;
                    overflow: hidden;
                `;
            }

            // ===== 四段式布局: [状态指示器] [图标] [中文名] [数值] [单位] =====

            // 1) 状态指示器点 (6px 圆点，语义化颜色)
            const indicator = document.createElement('span');
            indicator.className = 'fxm-capsule__indicator';
            indicator.dataset.metricType = metric.id;

            // 2) 图标容器 (SVG图标将由 addCapsuleIcon() 填充)
            const iconSpan = document.createElement('span');
            iconSpan.className = 'fxm-capsule__icon';
            // 图标内容由 addCapsuleIcon() 从 FXM_ICONS 库注入

            // 3) 中文标签
            const labelSpan = document.createElement('span');
            labelSpan.className = 'fxm-capsule__label fxm-label';
            labelSpan.textContent = metric.label;

            // 4) 数值
            const valueSpan = document.createElement('span');
            valueSpan.className = 'fxm-capsule__value fxm-value';
            valueSpan.textContent = metric.defaultVal;
            valueSpan.dataset.default = metric.defaultVal;

            // 5) 单位
            const unitSpan = document.createElement('span');
            unitSpan.className = 'fxm-capsule__unit fxm-unit';
            unitSpan.textContent = metric.unit;

            // 按顺序组装
            capsule.appendChild(indicator);
            capsule.appendChild(iconSpan);
            capsule.appendChild(labelSpan);
            capsule.appendChild(valueSpan);
            capsule.appendChild(unitSpan);

            // 将胶囊添加到底盘容器（而非直接添加到bar）
            tray.appendChild(capsule);

            // Task 2: 为胶囊添加 SVG 图标（替代原有 emoji）
            const iconType = METRIC_ICON_MAP[metric.id] || metric.id;
            addCapsuleIcon(capsule, iconType);
        });

        // 将底盘容器添加到顶部栏
        bar.appendChild(tray);

        document.body.appendChild(bar);

        // ★ Scheme A (Minimalist Pro) 实现验证日志 ★
        var schemeACapsules = document.querySelectorAll('.fxm-capsule.scheme-a');
        console.log('[飞雪监测器] ✅ 方案A (Minimalist Pro) 极简主义专业版已应用');
        console.log('[飞雪监测器]   胶囊尺寸: 26px (标准) / 32px (enhanced), 圆角: 9999px (完美胶囊)');
        console.log('[飞雪监测器]   底盘包含 ' + schemeACapsules.length + ' 个scheme-a胶囊 (四段式布局: [指示器][图标][名称][数值][单位])');
        console.log('[飞雪监测器]   设计特征: 极简扁平化 | rgba(255,255,255,0.04)背景 | Inter字体 | 6px状态指示器');
        console.log('[飞雪监测器]   验证命令: document.querySelectorAll(".fxm-capsule.scheme-a").length === 7');

        // 注入动画CSS
        injectAnimationStyles();

        return bar;
    }

    // ============================================================
    // 方案切换系统 (Scheme Switcher)
    // ============================================================

    /**
     * 切换UI方案 (scheme-a / scheme-b / scheme-c)
     *
     * **功能**:
     * - 动态切换所有胶囊的CSS方案类名
     * - 方案B时自动启动FPS监控和加载Orbitron字体
     * - 方案C时检测backdrop-filter兼容性并初始化性能优化
     * - 保存用户偏好到localStorage
     *
     * @param {string} schemeName - 目标方案名称 ('scheme-a', 'scheme-b' 或 'scheme-c')
     * @returns {boolean} 是否切换成功
     */
    function switchUIScheme(schemeName) {
        // 验证输入
        if (!schemeName || !CONFIG.availableSchemes.includes(schemeName)) {
            console.error('[飞雪] ❌ 无效的方案:', schemeName, '| 可用方案:', CONFIG.availableSchemes.join(' / '));
            return false;
        }

        const oldScheme = CONFIG.currentScheme;

        if (oldScheme === schemeName) {
            console.log('[飞雪] ℹ️ 当前已是 ' + schemeName + ', 无需切换');
            return true;
        }

        console.log('[飞雪] 🔄 正在切换方案: ' + oldScheme + ' → ' + schemeName);

        // 1. 切换所有胶囊的类名（移除所有旧方案类名，添加新方案类名）
        const allCapsules = document.querySelectorAll('.fxm-capsule');
        allCapsules.forEach(function(capsule) {
            // 移除所有方案类名
            capsule.classList.remove('scheme-a', 'scheme-b', 'scheme-c');

            // 添加新方案类名
            capsule.classList.add(schemeName);

            // 根据新方案重新应用基础样式
            if (schemeName === 'scheme-b') {
                // 方案B: Cyberpunk Tech 样式
                capsule.style.cssText = `
                    display: inline-flex;
                    align-items: center;
                    gap: calc(var(--fxm-capsule-gap, 6px) + 2px);
                    cursor: default;
                    user-select: none;
                    white-space: nowrap;
                    overflow: hidden;
                    position: relative;
                    transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
                `;
            } else if (schemeName === 'scheme-c') {
                // 方案C: Glassmorphism Refined 样式
                capsule.style.cssText = `
                    display: inline-flex;
                    align-items: center;
                    gap: 8px;
                    cursor: pointer;
                    user-select: none;
                    white-space: nowrap;
                    overflow: hidden;
                    position: relative;
                    transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
                `;
            } else {
                // 方案A: Minimalist Pro 样式
                capsule.style.cssText = `
                    display: flex;
                    align-items: center;
                    gap: 6px;
                    cursor: pointer;
                    transition: all 0.15s cubic-bezier(0.16, 1, 0.3, 1);
                    white-space: nowrap;
                    user-select: none;
                    position: relative;
                    overflow: hidden;
                `;
            }
        });

        // 2. 更新配置
        CONFIG.currentScheme = schemeName;

        // 3. 更新按钮状态（如果按钮组已创建）
        updateSchemeButtonStates(schemeName);

        // 4. 各方案特殊初始化
        if (schemeName === 'scheme-b') {
            // 方案B: 启动FPS性能监控 + 加载Orbitron字体
            if (typeof schemeB_PerformanceMonitor !== 'undefined') {
                schemeB_PerformanceMonitor.start(true);  // 强制重启
            }
            if (typeof loadOrbitronFont !== 'undefined') {
                loadOrbitronFont().then(function() {
                    console.log('[飞雪] ✅ Orbitron 字体已为方案B准备就绪');
                });
            }
            console.log('[飞雪] ✅ 方案B (Cyberpunk Tech) 已激活 | 特征: 霓虹发光/切角造型/扫描线/FPS自适应');

        } else if (schemeName === 'scheme-c') {
            // 方案C: 初始化兼容性检测和性能优化
            if (typeof initSchemeCCompatibility !== 'undefined') {
                initSchemeCCompatibility();
            }
            console.log('[飞雪] ✅ 方案C (Glassmorphism) 已激活 | 特征: 毛玻璃模糊/大圆角/精致质感');

        } else {
            // 方案A: 停止其他方案的特殊功能
            if (typeof schemeB_PerformanceMonitor !== 'undefined') {
                schemeB_PerformanceMonitor.stop();
            }
            // 清理可能残留的性能降级类
            allCapsules.forEach(function(capsule) {
                capsule.classList.remove('performance-degraded', 'low-fps', 'ultra-low-performance', 'no-glass');
            });
            console.log('[飞雪] ✅ 方案A (Minimalist Pro) 已激活 | 特征: 极简扁平化/完美胶囊/高可读性');
        }

        // 5. 保存用户偏好到localStorage
        try {
            localStorage.setItem('fxm-design-scheme', schemeName);
        } catch (e) {
            // localStorage不可用时静默失败
        }

        // 6. 导出全局API供外部调用
        window.fxmSwitchScheme = switchUIScheme;

        console.log('[飞雪] ✓ 切换完成 | 当前方案: ' + schemeName + ' (' + (((CONFIG.schemeLabels[schemeName] != null) ? CONFIG.schemeLabels[schemeName].title : '') || '') + ') | 胶囊数: ' + allCapsules.length);

        return true;
    }

    /**
     * 更新方案切换按钮组的选中状态
     * @param {string} activeScheme - 当前激活的方案名称
     */
    function updateSchemeButtonStates(activeScheme) {
        document.querySelectorAll('.fxm-scheme-btn').forEach(function(btn) {
            const btnScheme = btn.dataset.scheme;
            if (btnScheme === activeScheme) {
                btn.classList.add('active');
                // 选中态: 主题色边框 + 背景色填充
                btn.style.borderColor = 'var(--fxm-primary-color, #00ffff)';
                btn.style.background = 'rgba(0, 255, 255, 0.2)';
                btn.style.boxShadow = '0 0 8px rgba(0, 255, 255, 0.4)';
            } else {
                btn.classList.remove('active');
                // 默认态: 半透明背景
                btn.style.borderColor = 'transparent';
                btn.style.background = 'rgba(255, 255, 255, 0.08)';
                btn.style.boxShadow = 'none';
            }
        });
    }

    /**
     * 恢复上次保存的方案偏好
     * 支持新旧两种localStorage key的兼容
     */
    function restoreSavedScheme() {
        try {
            // 优先使用新key
            var savedScheme = localStorage.getItem('fxm-design-scheme');
            // 兼容旧key
            if (!savedScheme) {
                savedScheme = localStorage.getItem('fxm-current-scheme');
            }
            if (savedScheme && CONFIG.availableSchemes.includes(savedScheme)) {
                // 延迟执行，确保DOM已创建
                setTimeout(function() {
                    switchUIScheme(savedScheme);
                    console.log('[飞雪] 📂 已恢复用户方案偏好: ' + savedScheme + ' (' + (((CONFIG.schemeLabels[savedScheme] != null) ? CONFIG.schemeLabels[savedScheme].title : '') || '') + ')');
                }, 100);
            }
        } catch (e) {
            // localStorage不可用时静默失败
        }
    }

    // ============================================================
    // UI创建 - 悬浮监控面板
    // ============================================================
    let panelVisible = false;

    function createHoverPanel() {
        const panel = document.createElement('div');
        panel.id = 'fxm-hover-panel';
        panel.style.cssText = `
            position: fixed;
            top: 60px;
            right: 10px;
            width: 380px;
            ${getGlassStyle('high')}
            border: 2px solid #00ffff;
            border-radius: 16px;
            padding: 20px;
            z-index: 9998;
            display: none;
            box-shadow: 0 0 40px rgba(0, 255, 255, 0.3), inset 0 0 20px rgba(0, 255, 255, 0.1);
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            color: #00ff00;
            animation: fxm-fadeIn 0.3s ease-out;
        `;

        panel.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; padding-bottom: 10px; border-bottom: 1px solid rgba(0,255,255,0.3);">
                <h3 style="margin: 0; font-size: 18px; color: #00ffff; text-shadow: 0 0 10px #00ffff;">
                    ⚡ 飞雪监控
                </h3>
                <div id="fxm-panel-controls" style="display: flex; align-items: center; gap: 8px;">
                    <button onclick="window.fxmToggleTheme()" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border: none; border-radius: 50%; width: 24px; height: 24px; cursor: pointer;" title="主题"></button>
                    <button onclick="window.fxmMinimizePanel()" style="background: rgba(255,255,255,0.1); border: 1px solid #666; border-radius: 4px; width: 24px; height: 24px; cursor: pointer; color: #fff;">−</button>
                    <button onclick="window.fxmClosePanel()" style="background: rgba(255,0,0,0.3); border: 1px solid #f00; border-radius: 4px; width: 24px; height: 24px; cursor: pointer; color: #fff;">×</button>
                </div>
            </div>

            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-bottom: 20px;">
                <!-- CPU Card -->
                <div class="fxm-card" style="background: rgba(0,255,0,0.05); border: 1px solid rgba(0,255,0,0.3); border-radius: 12px; padding: 15px;">
                    <div style="font-size: 14px; opacity: 0.7; margin-bottom: 5px;">⚡ 处理器</div>
                    <div class="fxm-cpu-value" style="font-size: 32px; font-weight: bold; color: #00ff00;">--</div>
                    <div style="font-size: 12px; opacity: 0.5;">使用率</div>
                </div>

                <!-- RAM Card -->
                <div class="fxm-card" style="background: rgba(0,150,255,0.05); border: 1px solid rgba(0,150,255,0.3); border-radius: 12px; padding: 15px;">
                    <div style="font-size: 14px; opacity: 0.7; margin-bottom: 5px;">💾 内存</div>
                    <div class="fxm-ram-value" style="font-size: 32px; font-weight: bold; color: #00aaff;">--</div>
                    <div style="font-size: 12px; opacity: 0.5;">已用 GB</div>
                </div>

                <!-- GPU Card -->
                <div class="fxm-card" style="background: rgba(255,100,0,0.05); border: 1px solid rgba(255,100,0,0.3); border-radius: 12px; padding: 15px;">
                    <div style="font-size: 14px; opacity: 0.7; margin-bottom: 5px;">🎮 显卡</div>
                    <div class="fxm-gpu-value" style="font-size: 32px; font-weight: bold; color: #ff6400;">--</div>
                    <div style="font-size: 12px; opacity: 0.5;">使用率</div>
                </div>

                <!-- VRAM Card -->
                <div class="fxm-card" style="background: rgba(200,0,255,0.05); border: 1px solid rgba(200,0,255,0.3); border-radius: 12px; padding: 15px;">
                    <div style="font-size: 14px; opacity: 0.7; margin-bottom: 5px;">■ 显存</div>
                    <div class="fxm-vram-value" style="font-size: 32px; font-weight: bold; color: #c800ff;">--</div>
                    <div style="font-size: 12px; opacity: 0.5;">已用 GB</div>
                </div>
            </div>

            <!-- PRED Prediction Result Card (with Toggle Switch) -->
            <div class="fxm-pred-card" style="background: rgba(255,215,0,0.08); border: 1px solid rgba(255,215,0,0.4); border-radius: 12px; padding: 15px; margin-bottom: 15px; position: relative;">
                <!-- Card Header with Title and Toggle -->
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                    <div style="font-size: 14px; opacity: 0.8;">🧠 PRED 预测</div>
                    <!-- Toggle switch will be inserted here by createPredToggle() -->
                </div>

                <!-- Card Content Area (Task 4: 优化默认提示) -->
                <div class="fxm-pred-content">
                    <!-- Initial state: disabled with diamond icon -->
                    <div style="text-align:center;opacity:0.7;padding:15px;">
                        <div style="font-size:20px;margin-bottom:8px;">◆</div>
                        <div style="font-size:11px;font-weight:600;color:#00d4ff;">
                            PRED 就绪
                        </div>
                        <div style="font-size:9px;margin-top:6px;color:#888;line-height:1.4;">
                            点击开关启用预测功能
                        </div>
                    </div>
                </div>
            </div>

            <!-- Status Bar -->
            <div style="display: flex; justify-content: space-between; align-items: center; font-size: 11px; opacity: 0.5; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 10px;">
                <span>数据源: Browser-API</span>
                <span class="fxm-update-time">--:--:--</span>
            </div>
        `;

        document.body.appendChild(panel);

        // 插入性能/节能模式切换开关到面板标题栏（Task 4）
        const panelControls = document.getElementById('fxm-panel-controls');
        if (panelControls) {
            const modeToggle = createModeToggle();
            // 插入到主题按钮之前（第一个位置）
            panelControls.insertBefore(modeToggle, panelControls.firstChild);
            console.log('[飞雪监测器] ✅ 性能/节能模式切换开关已添加到面板');
        }

        // 插入方案切换按钮组(A/B/C)到面板标题栏
        if (panelControls) {
            const schemeSwitcher = createSchemeSwitcher();
            // 插入到modeToggle之后（第二个位置，在主题按钮之前）
            const modeToggleEl = document.getElementById('fxm-mode-toggle');
            if (modeToggleEl && modeToggleEl.nextSibling) {
                panelControls.insertBefore(schemeSwitcher, modeToggleEl.nextSibling);
            } else {
                // 如果modeToggle不存在或没有nextSibling，追加到末尾
                panelControls.appendChild(schemeSwitcher);
            }
            console.log('[飞雪] ✅ 方案切换按钮组(A/B/C)已添加到面板');
        }

        // 插入 PRED 预测开关到卡片标题栏（Task 5）
        const predCardHeader = panel.querySelector('.fxm-pred-card > div');
        if (predCardHeader) {
            const predToggle = createPredToggle();
            predCardHeader.appendChild(predToggle);
            console.log('[飞雪监测器] ✅ PRED 预测开关已插入');
        }

        return panel;
    }

    // ============================================================
    // 事件委托（替代直接绑定，防止内存泄漏）(Task 6 增强: 性能模式hover微浮起)
    // ============================================================
    function setupEventDelegation(bar) {
        // 点击事件 - 打开/关闭面板
        bar.addEventListener('click', (e) => {
            const capsule = e.target.closest('.fxm-capsule');
            if (capsule) togglePanel();
        });

        // 鼠标悬停效果 - 根据性能模式应用不同的交互反馈
        bar.addEventListener('mouseover', (e) => {
            const capsule = e.target.closest('.fxm-capsule');
            if (!capsule) return;

            // 检查当前是否为性能模式
            const isPerformanceMode = capsule.dataset.performanceMode === 'true';

            if (isPerformanceMode) {
                // ✨ 性能模式: 定向光源砖块微浮起效果
                // 向上浮动 2px + 增强定向阴影深度
                // ★ 所有高光颜色从主题色动态生成!
                var tc = getComputedStyle(document.documentElement).getPropertyValue('--fxm-primary').trim() || '#00ff41';

                capsule.style.transform = 'translateY(-2px) scale(1.02)';

                // 增强版定向光源阴影（保持定向性，使用主题色！）
                capsule.style.boxShadow =
                    /* 增强的主投影: 更深的右下投影 */
                    '7px 10px 20px rgba(0, 0, 0, 0.72), ' +
                    /* 增强的左侧高光 - 使用主题色! */
                    '-6px 0 14px ' + hexToRgba(lightenColor(tc, 45), 0.55) + ', ' +
                    /* 增强的顶部高光 - 使用主题色! */
                    '0 -6px 14px ' + hexToRgba(lightenColor(tc, 25), 0.32) + ', ' +
                    /* 内高光保持 */
                    'inset 0 2px 0 rgba(255, 255, 255, 0.28), ' +
                    /* 内暗边增强 */
                    'inset 0 -3px 0 rgba(0, 0, 0, 0.5), ' +
                    /* 内右侧暗边增强 */
                    'inset -4px 0 5px rgba(0, 0, 0, 0.3)';
            } else {
                // 🍃 节能模式: 简单的缩放效果（无浮起、无复杂阴影）
                capsule.style.transform = 'scale(1.05)';
                var glowColor = getComputedStyle(document.documentElement).getPropertyValue('--fxm-glow').trim() || 'rgba(0, 255, 255, 0.5)';
                capsule.style.boxShadow = '0 0 15px ' + glowColor;
            }
        });

        bar.addEventListener('mouseout', (e) => {
            const capsule = e.target.closest('.fxm-capsule');
            if (!capsule) return;

            // 检查当前是否为性能模式
            const isPerformanceMode = capsule.dataset.performanceMode === 'true';

            if (isPerformanceMode) {
                // 恢复到性能模式的定向光源砖块默认状态
                // ★ 使用主题色恢复阴影（与 applyPerformanceMode 保持一致）!
                var tc = getComputedStyle(document.documentElement).getPropertyValue('--fxm-primary').trim() || '#00ff41';

                capsule.style.transform = 'translateY(0) scale(1)';

                // 重新应用标准定向光源阴影（使用主题色，非硬编码！）
                capsule.style.boxShadow =
                    /* 1. 主投影: 向右下 */
                    '5px 7px 14px rgba(0, 0, 0, 0.65), ' +
                    /* 2. 左侧高光 - 使用主题色! */
                    '-5px 0 10px ' + hexToRgba(lightenColor(tc, 40), 0.45) + ', ' +
                    /* 3. 顶部高光 - 使用主题色! */
                    '0 -4px 10px ' + hexToRgba(lightenColor(tc, 20), 0.25) + ', ' +
                    /* 4. 内顶部反光 */
                    'inset 0 2px 0 rgba(255, 255, 255, 0.28), ' +
                    /* 5. 内底部暗边 */
                    'inset 0 -2px 0 rgba(0, 0, 0, 0.45), ' +
                    /* 6. 内右侧暗边 */
                    'inset -3px 0 4px rgba(0, 0, 0, 0.25)';
            } else {
                // 节能模式: 完全移除特效
                capsule.style.transform = 'scale(1)';
                capsule.style.boxShadow = '0 2px 4px rgba(0, 0, 0, 0.3)';
            }
        });
    }

    // ============================================================
    // 面板控制
    // ============================================================
    function togglePanel() {
        const panel = document.getElementById('fxm-hover-panel');
        if (!panel) return;

        panelVisible = !panelVisible;
        panel.style.display = panelVisible ? 'block' : 'none';
        
        if (panelVisible) {
            // 使用统一数据源获取最新数据并更新面板
            getUnifiedSystemData().then(data => {
                updatePanelData(data);
            });
        }
    }

    window.fxmClosePanel = function() {
        const panel = document.getElementById('fxm-hover-panel');
        if (panel) {
            panel.style.display = 'none';
            panelVisible = false;
        }
    };

    window.fxmMinimizePanel = function() {
        window.fxmClosePanel();
    };

    // ============================================================
    // 主题切换系统
    // ============================================================

    /**
     * 应用主题 - 🎨 只管颜色，完全不管模式！
     *
     * 核心原则: 主题系统与模式系统完全解耦
     * - 主题只负责: 颜色、发光、边框等视觉属性
     * - 模式只负责: 3D效果、毛玻璃、动画等性能属性
     * - 两者通过 CSS 变量协同工作，互不影响
     *
     * ⚠️ 绝对禁止在这里设置:
     * - element.style.background (那是 applyPerformanceMode 的职责)
     * - element.style.boxShadow (那是 applyPerformanceMode 的职责)
     * - element.style.backdropFilter (那是 applyPerformanceMode 的职责)
     *
     * @param {Object} theme - 主题配置对象
     */
    function applyTheme(theme) {
        const root = document.documentElement;

        // ============================================================
        // 第一步: 设置 CSS 变量（核心驱动机制）
        // 所有颜色相关的样式都通过这些变量自动更新
        // ============================================================
        root.style.setProperty('--fxm-primary', theme.primaryColor);
        root.style.setProperty('--fxm-secondary', theme.secondaryColor);
        root.style.setProperty('--fxm-bg', theme.bgColor);
        root.style.setProperty('--fxm-text', theme.textColor);
        root.style.setProperty('--fxm-glow', theme.glowColor);
        root.style.setProperty('--fxm-border', theme.borderColor);

        // ============================================================
        // 第二步: 更新需要直接设置颜色的元素
        // 这些元素的样式无法通过 CSS 变量自动继承
        //
        // ⚠️ 安全操作列表（只改颜色，不改背景/阴影/滤镜）:
        // ✅ borderColor, color, textShadow, opacity
        // ❌ background, boxShadow, backdropFilter (绝对禁止!)
        // ============================================================

        // 顶部胶囊栏 - 只更新边框和文字颜色（不管背景！）
        const capsules = document.querySelectorAll('.fxm-capsule');
        capsules.forEach(function(capsule) {
            // ★ Scheme A 主题适配: 极简主义胶囊使用克制的主题色变化 ★
            if (capsule.classList.contains('scheme-a')) {
                // Scheme A: 仅微调边框透明度，不改变核心视觉风格
                // 保持极简设计原则：主题变化应该是微妙且优雅的
                capsule.style.borderColor = '';  // 清空内联边框，使用CSS变量控制
                capsule.style.color = '';        // 清空内联颜色，使用CSS变量控制
                // 不设置 background, boxShadow, backdropFilter（绝对禁止！）
                // Scheme A的主题色变化通过CSS变量 --scheme-a-color-* 控制
                return;  // 跳过后续的内联样式设置
            }

            capsule.style.borderColor = theme.borderColor;
            capsule.style.color = theme.textColor;
            // ⚠️ 绝对不在这里设置 background 或 boxShadow！
            // 那是 applyPerformanceMode() 的职责
        });

        // 数值文字颜色（简化text-shadow，无朦胧感）
        const values = document.querySelectorAll('.fxm-value');
        values.forEach(function(val) {
            // ★ Scheme A 数值主题适配 ★
            var parentCapsule = val.closest('.fxm-capsule');
            if (parentCapsule && parentCapsule.classList.contains('scheme-a')) {
                // Scheme A: 移除text-shadow，保持最佳可读性
                // 数值颜色由状态类（status-normal/warning/danger）控制，不受主题影响
                val.style.textShadow = 'none';
                return;  // 跳过后续设置
            }

            val.style.color = theme.textColor;
            val.style.textShadow = '0 1px 2px rgba(0, 0, 0, 0.9)';  /* 单一清晰描边，替换原来的glow */
        });

        // 悬浮面板 - 只更新边框、发光、文字（不管背景和毛玻璃！）
        const panel = document.getElementById('fxm-hover-panel');
        if (panel) {
            panel.style.borderColor = theme.borderColor;
            // ⚠️ 绝对不在这里设置 boxShadow！
            // 那是 applyPerformanceMode() 的职责，主题切换不应覆盖它
            panel.style.color = theme.textColor;
            // ⚠️ 绝对不在这里设置 background 或 backdropFilter！

            // 面板标题颜色（简化text-shadow）
            var titleEl = panel.querySelector('h3');
            if (titleEl) {
                titleEl.style.color = theme.primaryColor;
                titleEl.style.textShadow = '0 1px 3px rgba(0, 0, 0, 0.8)';  /* 简化描边 */
            }

            // 面板分隔线
            var headerDiv = panel.querySelector('div[style*="border-bottom"]');
            if (headerDiv) {
                headerDiv.style.borderBottomColor = theme.glowColor.replace(/[\d.]+\)$/, '0.3)');
            }

            // 卡片边框
            var cards = panel.querySelectorAll('.fxm-card');
            cards.forEach(function(card) {
                card.style.borderColor = theme.glowColor.replace(/[\d.]+\)$/, '0.3)');
            });

            // PRED 卡片特殊边框色
            var predCard = panel.querySelector('div[style*="rgba(255,215,0)"]');
            if (predCard) {
                predCard.style.borderColor = theme.primaryColor.replace(/^#/, 'rgba(').replace(/(..)(..)(..)/, function(m, r, g, b) {
                    return parseInt(r, 16) + ',' + parseInt(g, 16) + ',' + parseInt(b, 16);
                }) + ',0.4)';
            }

            // PRED 数值颜色
            var predValue = panel.querySelector('.fxm-pred-value');
            if (predValue) {
                predValue.style.color = theme.primaryColor;
            }

            // 状态栏顶部分隔线
            var statusBar = panel.querySelector('div[style*="border-top"][style*="255,255,255"]');
            if (statusBar) {
                statusBar.style.borderTopColor = 'rgba(255,255,255,0.1)';
            }
        }

        // 主题按钮渐变色
        var themeBtn = document.querySelector('button[onclick*="fxmToggleTheme"]');
        if (themeBtn) {
            themeBtn.style.background = theme.buttonGradient;
        }

        // ✅ 不再调用 updateCapsuleThemeColors()
        // 原因: 该函数内部设置了 capsule.style.background 和 capsule.style.boxShadow
        // 这违反了解耦原则！主题系统不应该触碰这些属性。
        // 性能模式的视觉效果应该完全由 applyPerformanceMode() 管理。
        // 当用户切换主题时，CSS变量已更新，下次 applyPerformanceMode() 执行时会自动使用新颜色。

        console.log('[飞雪监测器] 🎨 主题已应用: ' + theme.name + ' (' + theme.primaryColor + ') [模式未改变]');
    }

    /**
     * 循环切换主题（全局函数，供按钮调用）
     * 使用 requestAnimationFrame 确保流畅过渡
     */
    window.fxmToggleTheme = function() {
        currentThemeIndex = (currentThemeIndex + 1) % THEMES.length;
        var newTheme = THEMES[currentThemeIndex];

        requestAnimationFrame(function() {
            applyTheme(newTheme);
        });

        // 持久化到 localStorage
        try {
            localStorage.setItem('fxm-theme-index', String(currentThemeIndex));
        } catch (e) {
            // localStorage 不可用时静默失败
        }

        console.log('[飞雪监测器] 🎨 主题已切换为: ' + newTheme.name);
    };

    /**
     * 恢复上次保存的主题
     */
    function restoreSavedTheme() {
        try {
            var saved = localStorage.getItem('fxm-theme-index');
            if (saved !== null) {
                var idx = parseInt(saved, 10);
                if (!isNaN(idx) && idx >= 0 && idx < THEMES.length) {
                    currentThemeIndex = idx;
                    applyTheme(THEMES[currentThemeIndex]);
                    console.log('[飞雪监测器] 🎨 已恢复主题: ' + THEMES[currentThemeIndex].name);
                }
            }
        } catch (e) {
            // localStorage 不可用时静默失败
        }
    }

    // ============================================================
    // 数据更新逻辑 - 适配真实数据格式（Task 7: 使用统一数据源）
    // ============================================================

    /**
     * Task 4 (P2): 更新PRED胶囊的特殊状态显示
     *
     * **设计原则**:
     * - PRED的状态语义与其他6个指标不同（基于risk_level而非百分比）
     * - 关闭/无数据时：灰色半透明（不丑陋但不抢眼）
     * - 开启且有数据时：根据预测风险等级动态着色
     *   - low: 蓝色 (#00d4ff) - 安全
     *   - medium: 黄色 (#ffaa00) - 注意
     *   - high/critical: 红色 (#ff3366) - 危险
     *   - unknown: 绿色 (#00ff88) - 默认
     *
     * @param {boolean} enabled - PRED开关是否开启
     * @param {Object|null} predictionData - 预测数据对象（可选）
     */
    function updatePredCapsuleAppearance(enabled, predictionData) {
        const predCapsule = document.querySelector('[data-metric="prediction"]');
        if (!predCapsule) return;

        const indicator = predCapsule.querySelector('.fxm-capsule__indicator');
        const valueEl = predCapsule.querySelector('.fxm-capsule__value');

        if (!enabled || !predictionData) {
            // ===== 关闭或无数据状态：灰色半透明 =====
            predCapsule.style.opacity = '0.65';

            if (indicator) {
                indicator.style.background = '#888888';
                indicator.style.boxShadow = 'none';
            }

            if (valueEl) {
                valueEl.style.color = '#aaaaaa';
                valueEl.textContent = '--';
            }

            // 移除所有状态类
            predCapsule.classList.remove('status-normal', 'status-warning', 'status-danger');
            predCapsule.classList.add('status-pred-disabled');

        } else {
            // ===== 有数据状态：根据risk_level着色 =====
            predCapsule.style.opacity = '1';

            const riskLevel = ((predictionData.risk_level != null) ? predictionData.risk_level.toLowerCase() : undefined) || 'unknown';
            let color;

            switch(riskLevel) {
                case 'low':
                    color = '#00d4ff';  /* 蓝色 - 安全 */
                    break;
                case 'medium':
                    color = '#ffaa00';  /* 黄色 - 注意 */
                    break;
                case 'high':
                case 'critical':
                    color = '#ff3366';  /* 红色 - 危险 */
                    break;
                default:
                    color = '#00ff88';  /* 默认绿色 */
            }

            if (indicator) {
                indicator.style.background = color;
                indicator.style.boxShadow = `0 0 6px ${color}80`;
            }

            if (valueEl && predictionData.success_rate !== null && predictionData.success_rate !== undefined) {
                valueEl.style.color = color;
                valueEl.textContent = (predictionData.success_rate * 100).toFixed(1);
            }

            // 设置状态类（用于图标着色和CSS选择器）
            predCapsule.classList.remove('status-normal', 'status-warning', 'status-danger', 'status-pred-disabled');
            if (riskLevel === 'high' || riskLevel === 'critical') {
                predCapsule.classList.add('status-danger');
            } else if (riskLevel === 'medium') {
                predCapsule.classList.add('status-warning');
            } else {
                predCapsule.classList.add('status-normal');
            }
        }
    }

    /**
     * Task 1: 语义化颜色系统 - 根据数值更新胶囊状态颜色
     *
     * **阈值规则**:
     * - 绿色 (#00ff88): < 60% - 正常
     * - 黄色 (#ffaa00): 60-80% - 警告
     * - 红色 (#ff3366): > 80% - 危险
     *
     * @param {HTMLElement} capsule - 胶囊 DOM 元素
     * @param {number|null} value - 当前数值
     * @param {string} metricType - 指标类型 ('cpu', 'ram', 'gpu', 'vram' 等)
     */
    function updateCapsuleStatus(capsule, value, metricType) {
        const indicator = capsule.querySelector('.fxm-capsule__indicator');
        const valueEl = capsule.querySelector('.fxm-capsule__value');

        if (!indicator || !valueEl) return;

        // 如果值为 null，恢复默认绿色状态
        if (value === null || value === undefined || isNaN(Number(value))) {
            indicator.style.background = '#00ff88';
            indicator.style.boxShadow = '0 0 6px rgba(0, 255, 136, 0.5)';
            valueEl.style.color = '';
            capsule.classList.remove('status-danger', 'status-warning');
            capsule.classList.add('status-normal');
            return;
        }

        let percentage = Number(value);
        let statusColor, textColor;

        // RAM/VRAM 需要特殊处理（绝对值转百分比估算）
        if (metricType === 'ram') {
            // 简单估算: >12GB=85%, >8GB=65%, 否则40%
            if (percentage > 12) percentage = 85;
            else if (percentage > 8) percentage = 65;
            else percentage = 40;
        } else if (metricType === 'vram') {
            // 简单估算: >5GB=85%, >3GB=65%, 否则45%
            if (percentage > 5) percentage = 85;
            else if (percentage > 3) percentage = 65;
            else percentage = 45;
        }

        // 根据百分比确定状态颜色
        if (percentage < 60) {
            statusColor = '#00ff88';   /* 绿色 - 正常 */
            textColor = '#00ffaa';
        } else if (percentage < 80) {
            statusColor = '#ffaa00';   /* 黄色 - 警告 */
            textColor = '#ffcc00';
        } else {
            statusColor = '#ff3366';   /* 红色 - 危险 */
            textColor = '#ff5577';
        }

        // 更新指示器颜色
        indicator.style.background = statusColor;
        indicator.style.boxShadow = `0 0 6px ${statusColor}80`;

        // 移除旧状态类
        capsule.classList.remove('status-normal', 'status-warning', 'status-danger');

        // 添加新状态类（触发 CSS 指示器颜色变化）
        if (percentage >= 80) {
            capsule.classList.add('status-danger');
        } else if (percentage >= 60) {
            capsule.classList.add('status-warning');
        } else {
            capsule.classList.add('status-normal');
        }

        // 更新数值文字颜色
        valueEl.style.color = textColor;
    }
    
    /**
     * 更新顶部胶囊显示 - 使用统一数据源
     * 
     * @param {Object} data - 统一的系统数据对象（由 getUnifiedSystemData() 提供）
     */
    function updateCapsules(data) {
        if (!data) {
            console.warn('[飞雪监测器] ⚠️ updateCapsules() 收到空数据');
            return;
        }

        // 标记此数据的消费者（用于调试一致性）
        if (data._consumers && !data._consumers.includes('capsule')) {
            data._consumers.push('capsule');
        }

        // 更新顶部胶囊 - 处理 null 值显示 '--'
        const updates = {
            // CPU 使用率
            'cpu': (data.cpu != null && data.cpu.usage != null && data.cpu.usage !== undefined)
                ? `${Number(data.cpu.usage).toFixed(1)}` : null,

            // RAM 已用 (GB)
            'ram': (data.ram != null && data.ram.used != null && data.ram.used !== undefined)
                ? `${Number(data.ram.used).toFixed(1)}` : null,

            // GPU 使用率
            'gpu': (data.gpu != null && data.gpu.usage != null && data.gpu.usage !== undefined)
                ? `${Number(data.gpu.usage).toFixed(1)}` : null,

            // VRAM 已用 (GB) - 尝试多个可能的字段名
            'vram': ((data.gpu != null && data.gpu.vram_used != null) ? data.gpu.vram_used : (data.gpu != null && data.gpu.vram_used_gb != null) ? data.gpu.vram_used_gb : undefined) != null
                ? `${Number(((data.gpu != null && data.gpu.vram_used != null) ? data.gpu.vram_used : (data.gpu != null && data.gpu.vram_used_gb != null) ? data.gpu.vram_used_gb : undefined)).toFixed(1)}` : null,

            // 预测成功率（Task 4: 使用PRED专用外观函数）
            'prediction': (predEnabled && (data.prediction != null && data.prediction.success_rate != null))
                ? `${Number(data.prediction.success_rate).toFixed(1)}`
                : null,

            // 预留显存 (MB) - 暂无数据来源
            'rsv': data.reserved_mb != null ? `${data.reserved_mb}` : null,

            // 功耗 (W) - 尝试多个可能的字段名
            'power': ((data.power != null && data.power.draw_w != null) ? data.power.draw_w : (data.gpu != null && data.gpu.power_usage_w != null) ? data.gpu.power_usage_w : undefined) != null
                ? `${Math.round(Number(((data.power != null && data.power.draw_w != null) ? data.power.draw_w : (data.gpu != null && data.gpu.power_usage_w != null) ? data.gpu.power_usage_w : undefined)))}` : null
        };

        let updatedCount = 0;
        Object.entries(updates).forEach(([id, value]) => {
            const capsule = document.querySelector(`[data-metric="${id}"]`);
            if (!capsule) {
                console.warn(`[飞雪监测器] ⚠️ 找不到胶囊元素: [data-metric="${id}"]`);
                return;
            }

            const valueEl = capsule.querySelector('.fxm-value');
            if (!valueEl) {
                console.warn(`[飞雪监测器] ⚠️ 找不到数值元素: [data-metric="${id}"] .fxm-value`);
                return;
            }

            if (value === null || value === 'null') {
                valueEl.textContent = valueEl.dataset.default || '--';
                valueEl.style.opacity = '0.5';

                // Task 4: PRED指标使用专用外观函数（基于risk_level而非百分比）
                if (id === 'prediction') {
                    updatePredCapsuleAppearance(predEnabled, null);
                } else {
                    // 其他6个指标使用通用的语义化颜色系统
                    updateCapsuleStatus(capsule, null, id);
                }
            } else {
                valueEl.textContent = value;
                valueEl.style.opacity = '1';
                updatedCount++;

                // Task 4: PRED指标使用专用外观函数
                if (id === 'prediction' && data.prediction) {
                    updatePredCapsuleAppearance(predEnabled, data.prediction);
                } else {
                    // 其他6个指标使用通用的语义化颜色系统
                    updateCapsuleStatus(capsule, Number(value), id);
                }
            }
        });

        if (updatedCount > 0) {
            console.log(`[飞雪监测器] 💊 胶囊已更新 (${updatedCount}/7):`, {
                cpu: ((_qs = document.querySelector('[data-metric="cpu"] .fxm-value')) != null ? _qs.textContent : undefined),
                ram: ((_qs = document.querySelector('[data-metric="ram"] .fxm-value')) != null ? _qs.textContent : undefined),
                gpu: ((_qs = document.querySelector('[data-metric="gpu"] .fxm-value')) != null ? _qs.textContent : undefined),
            });
        }
    }

    /**
     * 更新面板数据 - 使用统一数据源（Task 7 修复）
     * 
     * **重要变更**:
     * - 不再内部调用 collectSystemData()（避免双重数据获取导致不一致）
     * - 改为接收外部传入的统一数据对象
     * - 与胶囊共享同一份数据引用，确保数值完全一致
     * 
     * @param {Object} data - 统一的系统数据对象（由 getUnifiedSystemData() 提供）
     */
    function updatePanelData(data) {
        // 如果没有传入数据，尝试从缓存获取（向后兼容）
        if (!data) {
            console.warn('[飞雪监测器] ⚠️ updatePanelData() 未收到参数，尝试使用缓存数据');
            data = cachedSystemData;
        }
        
        if (!data) {
            console.warn('[飞雪监测器] ⚠️ 无可用数据，跳过面板更新');
            return;
        }
        
        // 标记此数据的消费者（用于调试）
        if (data._consumers && !data._consumers.includes('panel')) {
            data._consumers.push('panel');
        }

        // 更新面板卡片 - 使用传入的统一数据
        const cpuEl = document.querySelector('.fxm-cpu-value');
        if (cpuEl) {
            if ((data.cpu != null && data.cpu.usage != null)) {
                cpuEl.textContent = `${data.cpu.usage.toFixed(1)}%`;
                cpuEl.style.opacity = '1';
            } else {
                cpuEl.textContent = '--';
                cpuEl.style.opacity = '0.5';
            }
        }

        const ramEl = document.querySelector('.fxm-ram-value');
        if (ramEl) {
            if ((data.ram != null && data.ram.used != null)) {
                ramEl.textContent = data.ram.used.toFixed(1);
                ramEl.style.opacity = '1';
            } else {
                ramEl.textContent = '--';
                ramEl.style.opacity = '0.5';
            }
        }

        const gpuEl = document.querySelector('.fxm-gpu-value');
        if (gpuEl) {
            if ((data.gpu != null && data.gpu.usage != null)) {
                gpuEl.textContent = `${data.gpu.usage.toFixed(1)}%`;
                gpuEl.style.opacity = '1';
            } else {
                gpuEl.textContent = 'N/A';
                gpuEl.style.opacity = '0.5';
            }
        }

        const vramEl = document.querySelector('.fxm-vram-value');
        if (vramEl) {
            if ((data.gpu != null && data.gpu.vram_used != null)) {
                vramEl.textContent = data.gpu.vram_used.toFixed(1);
                vramEl.style.opacity = '1';
            } else {
                vramEl.textContent = 'N/A';
                vramEl.style.opacity = '0.5';
            }
        }

        const predEl = document.querySelector('.fxm-pred-value');
        if (predEl) {
            // 仅在预测功能启用时更新数据
            if (predEnabled && (data.prediction != null && data.prediction.success_rate != null)) {
                predEl.textContent = `${data.prediction.success_rate.toFixed(1)}%`;
                predEl.style.opacity = '1';
            } else if (!predEnabled) {
                // 保持禁用状态，不更新
                return;  // 跳过后续的 risk 更新
            } else {
                predEl.textContent = '--';
                predEl.style.opacity = '0.5';
            }
        }

        const riskEl = document.querySelector('.fxm-pred-risk');
        if (riskEl && predEnabled && data.prediction) {
            riskEl.textContent = `RISK: ${data.prediction.risk_level || 'UNKNOWN'}`;
        }

        // 更新数据来源显示 - 显示真实来源信息
        const sourceEl = document.querySelector('#fxm-hover-panel .fxm-update-time');
        if (sourceEl) {
            const now = new Date();
            const timeStr = now.toLocaleTimeString();
            
            // 根据数据来源显示不同颜色和文本
            let sourceInfo = '';
            if (data._backend_available === true) {
                sourceInfo = data.data_source_desc || 'Backend-API ✓';
            } else if (data._backend_available === false) {
                sourceInfo = '后端不可用 ✗';
            } else {
                sourceInfo = data.data_source_desc || 'Unknown';
            }
            
            sourceEl.textContent = `${timeStr} | ${sourceInfo}`;
            
            // 根据可用性设置颜色
            if (data._backend_available === false) {
                sourceEl.style.color = '#ff6b6b';  // 红色表示不可用
            } else if (data._backend_available === true) {
                sourceEl.style.color = '#00ff00';   // 绿色表示正常
            } else {
                sourceEl.style.color = '#ffffff';   // 白色默认
            }
        }

        // 详细日志（包含一致性验证信息）
        console.log(`[飞雪监测器] 📊 面板已更新:`, {
            timestamp: new Date().toLocaleTimeString(),
            cpu: `${(data.cpu != null ? data.cpu.usage : undefined)}%`,
            ram: `${(data.ram != null ? data.ram.used : undefined)}GB (${(data.ram != null ? data.ram.percent : undefined)}%)`,
            gpu: `${(data.gpu != null ? data.gpu.usage : undefined)}%`,
            vram: `${(data.gpu != null ? data.gpu.vram_used : undefined)}GB`,
            _unifiedTimestamp: data._unifiedTimestamp ? new Date(data._unifiedTimestamp).toLocaleTimeString() : 'N/A',
            consumers: data._consumers || ['unknown'],
            dataSource: data.data_source,
        });
    }

    // ============================================================
    // CSS动画注入 (Task 3: 增加底盘和3D增强样式)
    // ============================================================
    function injectAnimationStyles() {
        if (document.getElementById('fxm-styles')) return;

        const style = document.createElement('style');
        style.id = 'fxm-styles';
        style.textContent = `
            @keyframes fxm-slideIn {
                from {
                    opacity: 0;
                    transform: translateX(50px);
                }
                to {
                    opacity: 1;
                    transform: translateX(0);
                }
            }

            @keyframes fxm-fadeIn {
                from { opacity: 0; transform: translateY(-10px); }
                to { opacity: 1; transform: translateY(0); }
            }

            @keyframes fxm-spin {
                0% { transform: rotate(0deg); }
                100% { transform: rotate(360deg); }
            }

            /* ===== Task 1: 胶囊底盘容器 - 深色凹陷效果（截图2风格增强版）===== */
            .fxm-capsule-tray {
                background: linear-gradient(
                    180deg,
                    #1a1e2e 0%,
                    #141824 50%,
                    #10141f 100%
                );
                border-radius: 22px;           /* 从20px增至22px（更大圆角） */
                padding: 10px 16px;             /* 从8px 14px增至10px 16px（更多内边距） */
                box-shadow:
                    inset 0 3px 8px rgba(0, 0, 0, 0.7),  /* 更深凹陷（从0.6增至0.7） */
                    0 6px 20px rgba(0, 0, 0, 0.5);         /* 更强外影（从0.4增至0.5） */
                display: flex;
                align-items: center;
                gap: 8px;
                flex-wrap: nowrap;
            }

            /* ===== Task 1: 性能模式下的增强底盘 ===== */
            .fxm-capsule-tray.enhanced {
                box-shadow:
                    inset 0 2px 6px rgba(0, 0, 0, 0.6),
                    0 4px 16px var(--fxm-glow, rgba(0, 255, 65, 0.15));
            }

            /* ===== Task 1: 节能模式下的简洁底盘 ===== */
            .fxm-capsule-tray.simple {
                box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.5);
            }

            /* ================================================================
               定向光源方正砖块风格 (Directional Light Brick Style)

               光源位置: 左上方 (-x, -y方向)
               效果: 左侧和顶部有高光，右侧和底部有阴影
               立体感: 像一块倾斜的砖/卡片，而非圆润的球体
               核心改变: 删除所有四周均匀的glow效果！
               ================================================================ */
            .fxm-capsule.enhanced {
                /* 背景: 微渐变增强体积（不要太强，保持清爽） */
                background: linear-gradient(
                    135deg,
                    rgba(45, 50, 75, 0.97) 0%,
                    rgba(28, 33, 52, 0.99) 50%,
                    rgba(18, 22, 38, 0.97) 100%
                ) !important;

                /* 边框: 仅左侧和顶部有轻微亮边，模拟左上光源 */
                border: 1px solid;
                border-color:
                    rgba(255, 255, 255, 0.18)   /* 上边最亮 */
                    rgba(255, 255, 255, 0.08)   /* 右边暗 */
                    rgba(255, 255, 255, 0.08)   /* 下边暗 */
                    rgba(255, 255, 255, 0.15) !important; /* 左边次亮 */

                /* ★★★ 定向光源阴影系统（使用CSS变量，随主题自动变化）★★★ */
                box-shadow:
                    /* 1. 主投影: 向右下 (模拟左上光源投射阴影) */
                    5px 7px 14px rgba(0, 0, 0, 0.65),
                    /* 2. ★ 左侧高光!: 使用主题色变量! */
                    -5px 0 10px color-mix(in srgb, var(--fxm-primary, #00ff41) 45%, transparent),
                    /* 3. 顶部高光: 使用主题色变量! */
                    0 -4px 10px color-mix(in srgb, var(--fxm-primary, #00ff41) 25%, transparent),
                    /* 4. 内顶部反光 (受光面) */
                    inset 0 2px 0 rgba(255, 255, 255, 0.28),
                    /* 5. 内底部暗边 (背光面) */
                    inset 0 -2px 0 rgba(0, 0, 0, 0.45),
                    /* 6. 内右侧暗边 (背光面) */
                    inset -3px 0 4px rgba(0, 0, 0, 0.25);

                transition: all 0.3s ease;
            }

            /* ===== Task 1: 节能模式下的简洁胶囊 (.simple) ===== */
            .fxm-capsule.simple {
                background: rgba(30, 30, 40, 0.95) !important;
                box-shadow: 0 2px 4px rgba(0, 0, 0, 0.3) !important;
            }

            /* ===== Task 1: 状态指示器点 (6px 圆形) ===== */
            .fxm-capsule__indicator {
                display: inline-block;
                width: 6px;
                height: 6px;
                border-radius: 50%;
                flex-shrink: 0;
                background: #00ff88;
                box-shadow: 0 0 6px rgba(0, 255, 136, 0.5);
                transition: all 0.3s ease;
            }

            /* 状态指示器 - 危险 (红) */
            .status-danger .fxm-capsule__indicator {
                background: #ff3366;
                box-shadow: 0 0 6px rgba(255, 51, 102, 0.5);
            }

            /* 状态指示器 - 警告 (黄) */
            .status-warning .fxm-capsule__indicator {
                background: #ffaa00;
                box-shadow: 0 0 6px rgba(255, 170, 0, 0.5);
            }

            /* 状态指示器 - 正常 (绿) */
            .status-normal .fxm-capsule__indicator {
                background: #00ff88;
                box-shadow: 0 0 6px rgba(0, 255, 136, 0.5);
            }

            /* ===== Task 1: 文字区域保护 + 四段式子元素样式 ===== */
            .fxm-capsule__icon,
            .fxm-capsule__label,
            .fxm-capsule__value,
            .fxm-capsule__unit {
                position: relative;
                z-index: 10;
            }

            /* 数值文字 - 清晰锐利，无朦胧感（定向光源砖块风格） */
            .fxm-capsule__value {
                font-weight: 800;              /* 超粗体 */
                font-size: 13px;
                text-shadow: 0 1px 2px rgba(0, 0, 0, 0.9);  /* 单一清晰描边，删除多层模糊！ */
                min-width: 28px;               /* 从40px减至28px（节省空间） */
                text-align: left;              /* 左对齐！不再右对齐导致溢出 */
                position: relative;
                z-index: 20;
            }

            /* 中文标签 - 较小字号，半透明 */
            .fxm-capsule__label {
                font-size: 10px;
                opacity: 0.75;
                white-space: nowrap;
                text-shadow: 0 1px 2px rgba(0, 0, 0, 0.8);   /* 简化描边，删除强模糊 */
                z-index: 20;
            }

            /* 单位 - 最小字号，确保不被截断 */
            .fxm-capsule__unit {
                font-size: 9px;
                opacity: 0.6;
                margin-left: 1px;               /* 从2px减小到1px */
                padding-right: 3px;             /* 右侧留白确保%符号可见 */
                text-shadow: 0 1px 2px rgba(0, 0, 0, 0.8);    /* 简化描边 */
                z-index: 20;
                white-space: nowrap;
            }

            /* 默认 hover 效果（定向光源增强，使用CSS变量随主题变化） */
            .fxm-capsule:hover {
                transform: translateY(-2px) scale(1.02) !important;
                box-shadow:
                    7px 10px 20px rgba(0, 0, 0, 0.72),
                    -6px 0 14px color-mix(in srgb, var(--fxm-primary, #00ff41) 55%, transparent),
                    0 -6px 14px color-mix(in srgb, var(--fxm-primary, #00ff41) 32%, transparent),
                    inset 0 2px 0 rgba(255, 255, 255, 0.28),
                    inset 0 -3px 0 rgba(0, 0, 0, 0.5),
                    inset -4px 0 5px rgba(0, 0, 0, 0.3) !important;
            }

            #fxm-hover-panel {
                transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            }

            /* PRED Toggle Switch Styles (Task 5) */
            .fxm-pred-toggle-container {
                z-index: 10;
            }

            .fxm-pred-toggle:hover {
                opacity: 0.9;
            }

            .fxm-pred-toggle:active .fxm-pred-knob {
                width: 16px;
            }

            .fxm-spinner {
                display: inline-block;
                width: 20px;
                height: 20px;
                border: 2px solid rgba(255, 215, 0, 0.3);
                border-top-color: #ffd700;
                border-radius: 50%;
                animation: fxm-spin 0.8s linear infinite;
            }

            /* PRED Metrics Layout */
            .fxm-pred-metrics {
                display: flex;
                justify-content: space-around;
                align-items: center;
                padding: 10px 0;
            }

            .fxm-pred-item {
                display: flex;
                flex-direction: column;
                align-items: center;
                gap: 4px;
            }

            .fxm-pred-label {
                font-size: 11px;
                opacity: 0.6;
            }

            .fxm-pred-value {
                font-size: 20px;
                font-weight: bold;
            }

            /* ===== Task 2: SVG 图标容器样式 ===== */
            /* 图标容器基础样式 */
            .fxm-capsule__icon {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                width: 16px;
                height: 16px;
                margin-right: 6px;
                flex-shrink: 0;
            }

            /* 图标内部 SVG 自适应 */
            .fxm-capsule__icon svg {
                width: 100%;
                height: 100%;
                overflow: visible;
            }

            /* 图标动态着色支持 - 正常状态 (绿) */
            .fxm-capsule.status-normal .fxm-capsule__icon {
                color: #00ff88;
                filter: drop-shadow(0 0 4px rgba(0, 255, 136, 0.6));
            }

            /* 图标动态着色支持 - 警告状态 (黄) */
            .fxm-capsule.status-warning .fxm-capsule__icon {
                color: #ffaa00;
                filter: drop-shadow(0 0 4px rgba(255, 170, 0, 0.6));
            }

            /* 图标动态着色支持 - 危险状态 (红) */
            .fxm-capsule.status-danger .fxm-capsule__icon {
                color: #ff3366;
                filter: drop-shadow(0 0 4px rgba(255, 51, 102, 0.6));
            }

            /* ===== Task 4: PRED 胶囊专用样式（融入新HUD风格）===== */

            /* PRED禁用状态 - 灰色半透明但不丑陋 */
            .fxm-capsule.status-pred-disabled {
                opacity: 0.65;
            }

            .fxm-capsule.status-pred-disabled .fxm-capsule__indicator {
                background: #888888 !important;
                box-shadow: none !important;
            }

            .fxm-capsule.status-pred-disabled .fxm-capsule__value {
                color: #aaaaaa !important;
            }

            .fxm-capsule.status-pred-disabled .fxm-capsule__icon {
                color: #666666 !important;
                filter: drop-shadow(0 0 2px rgba(102, 102, 102, 0.3)) !important;
            }

            /* PRED卡片在面板内保持简洁优雅（降低背景强度） */
            .fxm-pred-card {
                background: rgba(255, 215, 0, 0.06) !important;  /* 降低背景强度 */
                border: 1px solid rgba(255, 215, 0, 0.25) !important;  /* 弱化边框 */
                border-radius: 12px;
                transition: all 0.3s ease;
            }

            /* PRED卡片hover效果（轻微高亮） */
            .fxm-pred-card:hover {
                background: rgba(255, 215, 0, 0.1) !important;
                border-color: rgba(255, 215, 0, 0.35) !important;
                box-shadow: 0 0 15px rgba(255, 215, 0, 0.15);
            }

            /* PRED内容区域文字优化 */
            .fxm-pred-content {
                min-height: 80px;
                display: flex;
                align-items: center;
                justify-content: center;
            }

            /* ============================================================================
               SCHEME A: MINIMALIST PRO (极简主义专业版) - 完整实现
               
               设计特征:
               - 高度: 32px (enhanced) / 26px (standard)
               - 圆角: 9999px (完美胶囊)
               - 背景: rgba(255,255,255,0.04) 极浅
               - 边框: 1px solid rgba(255,255,255,0.08)
               - 阴影: 无或极浅 (极度克制)
               - 字体: Inter, 12px, font-weight: 500
               - 内部间距: padding 8px 16px
               - 状态指示器: 6px圆形
               ============================================================================ */

            /* ---- Scheme A: Design Tokens (CSS变量) ---- */
            :root {
                --scheme-a-bg-primary:     #0A0A0A;
                --scheme-a-bg-secondary:   #171717;
                --scheme-a-text-primary:   #F3F4F6;
                --scheme-a-text-secondary: #9CA3AF;
                --scheme-a-text-muted:     #6B7280;
                --scheme-a-color-success:  #10B981;
                --scheme-a-color-warning:  #F59E0B;
                --scheme-a-color-danger:   #EF4444;
                --scheme-a-color-info:      #3B82F6;
                --scheme-a-border-default: rgba(255, 255, 255, 0.08);
                --scheme-a-border-subtle:  rgba(255, 255, 255, 0.06);
                --scheme-a-border-hover:   rgba(255, 255, 255, 0.15);
                --scheme-a-capsule-bg:           rgba(255, 255, 255, 0.04);
                --scheme-a-capsule-bg-hover:     rgba(255, 255, 255, 0.08);
                --scheme-a-capsule-border:       1px solid rgba(255, 255, 255, 0.08);
                --scheme-a-capsule-border-hover: 1px solid rgba(255, 255, 255, 0.15);
                --scheme-a-shadow-sm:      0 1px 2px rgba(0, 0, 0, 0.15);
                --scheme-a-shadow-md:      0 2px 8px rgba(0, 0, 0, 0.12);
            }

            /* ---- Scheme A: Capsule Component (核心胶囊样式) ---- */
            .fxm-capsule.scheme-a {
                /* 布局 */
                position: relative;
                display: inline-flex;
                align-items: center;
                gap: 6px;

                /* 尺寸 - 标准26px，可通过.enhanced升级到32px */
                height: 26px;
                padding: 6px 14px;

                /* 视觉 - 极简扁平化 */
                background: var(--scheme-a-capsule-bg);
                border: var(--scheme-a-capsule-border);
                border-radius: 9999px;  /* 完美胶囊形 */

                /* 字体 - Inter风格，清晰可读 */
                font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                font-size: 12px;
                font-weight: 500;
                letter-spacing: -0.015em;
                color: var(--scheme-a-text-primary);

                /* 交互 */
                cursor: default;
                user-select: none;
                white-space: nowrap;
                overflow: hidden;

                /* 过渡 - 快速响应 */
                transition:
                    background-color 150ms cubic-bezier(0.16, 1, 0.3, 1),
                    border-color 150ms cubic-bezier(0.16, 1, 0.3, 1),
                    transform 150ms cubic-bezier(0.16, 1, 0.3, 1),
                    box-shadow 150ms cubic-bezier(0.16, 1, 0.3, 1);

                /* 重置内联样式优先级 */
                min-width: auto !important;
                width: auto !important;
            }

            /* Scheme A: Hover State - 微妙提升 */
            .fxm-capsule.scheme-a:hover {
                background: var(--scheme-a-capsule-bg-hover);
                border-color: var(--scheme-a-capsule-border-hover);
                transform: translateY(-1px);
                box-shadow: var(--scheme-a-shadow-sm);
            }

            /* Scheme A: Active/Pressed State */
            .fxm-capsule.scheme-a:active {
                transform: translateY(0) scale(0.98);
            }

            /* Scheme A: Focus Visible (键盘导航可访问性) */
            .fxm-capsule.scheme-a:focus-visible {
                outline: 2px solid transparent;
                outline-offset: 2px;
                outline-color: rgba(16, 185, 129, 0.5);
            }

            /* ---- Scheme A: Enhanced Variant (增强版 - 更大更突出) ---- */
            .fxm-capsule.scheme-a.enhanced {
                height: 32px !important;
                padding: 8px 16px !important;
                gap: 8px;
            }

            /* ---- Scheme A: Status Indicator (状态指示灯 - 6px圆形) ---- */
            .fxm-capsule.scheme-a .fxm-capsule__indicator,
            .fxm-capsule.scheme-a .fxm-indicator {
                width: 6px;
                height: 6px;
                border-radius: 9999px;
                flex-shrink: 0;
                background: var(--scheme-a-color-success);
                box-shadow: none;
                transition:
                    background-color 250ms cubic-bezier(0.4, 0, 0.2, 1),
                    box-shadow 250ms cubic-bezier(0.4, 0, 0.2, 1);
            }

            /* Normal (<60%) - 绿色稳定 */
            .fxm-capsule.scheme-a.status-normal .fxm-capsule__indicator,
            .fxm-capsule.scheme-a.status-normal .fxm-indicator,
            .fxm-capsule.scheme-a .fxm-capsule__indicator--normal,
            .fxm-capsule.scheme-a .fxm-indicator--normal {
                background-color: var(--scheme-a-color-success);
                box-shadow: 0 0 0 0 rgba(16, 185, 129, 0);
                animation: none;
            }

            /* Warning (60-80%) - 琥珀色轻微脉冲 */
            .fxm-capsule.scheme-a.status-warning .fxm-capsule__indicator,
            .fxm-capsule.scheme-a.status-warning .fxm-indicator,
            .fxm-capsule.scheme-a .fxm-capsule__indicator--warning,
            .fxm-capsule.scheme-a .fxm-indicator--warning {
                background-color: var(--scheme-a-color-warning);
                box-shadow: 0 0 0 0 rgba(245, 158, 11, 0);
                animation: scheme-a-pulse-warning 2s ease-in-out infinite;
            }

            /* Danger (>80%) - 红色明显脉冲 */
            .fxm-capsule.scheme-a.status-danger .fxm-capsule__indicator,
            .fxm-capsule.scheme-a.status-danger .fxm-indicator,
            .fxm-capsule.scheme-a .fxm-capsule__indicator--danger,
            .fxm-capsule.scheme-a .fxm-indicator--danger {
                background-color: var(--scheme-a-color-danger);
                box-shadow: 0 0 0 0 rgba(239, 68, 68, 0);
                animation: scheme-a-pulse-danger 1.5s ease-in-out infinite;
            }

            /* Inactive/Disabled */
            .fxm-capsule.scheme-a.status-inactive .fxm-capsule__indicator,
            .fxm-capsule.scheme-a.status-inactive .fxm-indicator,
            .fxm-capsule.scheme-a.status-pred-disabled .fxm-capsule__indicator,
            .fxm-capsule.scheme-a.status-pred-disabled .fxm-indicator {
                background-color: rgba(255, 255, 255, 0.2);
                box-shadow: none;
                animation: none;
            }

            /* ---- Scheme A: Icon (图标 - 14px) ---- */
            .fxm-capsule.scheme-a .fxm-capsule__icon,
            .fxm-capsule.scheme-a .fxm-icon {
                width: 14px;
                height: 14px;
                display: flex;
                align-items: center;
                justify-content: center;
                flex-shrink: 0;
                color: var(--scheme-a-text-secondary);
                margin-right: 0;  /* 重置原有margin */
                transition: color 150ms cubic-bezier(0.16, 1, 0.3, 1);
                filter: none;  /* 移除drop-shadow */
            }

            .fxm-capsule.scheme-a .fxm-capsule__icon svg,
            .fxm-capsule.scheme-a .fxm-icon svg {
                width: 100%;
                height: 100%;
                fill: currentColor;
            }

            /* Icon colors by status */
            .fxm-capsule.scheme-a.status-normal .fxm-capsule__icon,
            .fxm-capsule.scheme-a.status-normal .fxm-icon { color: var(--scheme-a-color-success); }
            .fxm-capsule.scheme-a.status-warning .fxm-capsule__icon,
            .fxm-capsule.scheme-a.status-warning .fxm-icon { color: var(--scheme-a-color-warning); }
            .fxm-capsule.scheme-a.status-danger .fxm-capsule__icon,
            .fxm-capsule.scheme-a.status-danger .fxm-icon { color: var(--scheme-a-color-danger); }
            .fxm-capsule.scheme-a:hover .fxm-capsule__icon,
            .fxm-capsule.scheme-a:hover .fxm-icon { color: var(--scheme-a-text-primary); }

            /* ---- Scheme A: Label (中文标签) ---- */
            .fxm-capsule.scheme-a .fxm-capsule__label {
                font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                font-size: 11px;
                font-weight: 500;
                color: var(--scheme-a-text-secondary);
                opacity: 1;  /* 重置opacity */
                text-shadow: none;  /* 移除text-shadow */
                white-space: nowrap;
                letter-spacing: 0.02em;
            }

            /* ---- Scheme A: Value (数值 - 等宽字体，高可读性) ---- */
            .fxm-capsule.scheme-a .fxm-capsule__value,
            .fxm-capsule.scheme-a .fxm-value {
                font-family: 'JetBrains Mono', 'SF Mono', 'Fira Code', 'Cascadia Code', Consolas, monospace;
                font-size: 14px;
                font-weight: 700;
                line-height: 1;
                color: var(--scheme-a-text-primary);
                text-shadow: none;  /* 移除text-shadow保证最佳可读性 */
                min-width: auto !important;
                text-align: left;
                font-feature-settings: 'tnum' on, 'lnum' on;
                transition: color 250ms cubic-bezier(0.4, 0, 0.2, 1);
            }

            /* Value colors by status (可选：让数值也带语义色) */
            .fxm-capsule.scheme-a.status-normal .fxm-capsule__value,
            .fxm-capsule.scheme-a.status-normal .fxm-value { color: var(--scheme-a-color-success); }
            .fxm-capsule.scheme-a.status-warning .fxm-capsule__value,
            .fxm-capsule.scheme-a.status-warning .fxm-value { color: var(--scheme-a-color-warning); }
            .fxm-capsule.scheme-a.status-danger .fxm-capsule__value,
            .fxm-capsule.scheme-a.status-danger .fxm-value { color: var(--scheme-a-color-danger); }

            /* ---- Scheme A: Unit (单位) ---- */
            .fxm-capsule.scheme-a .fxm-capsule__unit,
            .fxm-capsule.scheme-a .fxm-unit {
                font-family: 'JetBrains Mono', 'SF Mono', 'Fira Code', Consolas, monospace;
                font-size: 11px;
                font-weight: 500;
                line-height: 1;
                color: var(--scheme-a-text-secondary);
                margin-left: 1px;
                padding-right: 0;  /* 重置padding */
                text-transform: uppercase;
                letter-spacing: 0.05em;
                opacity: 1;  /* 重置opacity */
                text-shadow: none;
                white-space: nowrap;
                transition: color 150ms cubic-bezier(0.16, 1, 0.3, 1);
            }

            /* ---- Scheme A: Performance Mode Enhancements (性能模式增强) ---- */
            .fxm-capsule.scheme-a.enhanced {
                /* 性能模式：极浅阴影和边框高亮（克制差异） */
                box-shadow: var(--scheme-a-shadow-md);
                border-color: rgba(255, 255, 255, 0.12);
            }

            .fxm-capsule.scheme-a.enhanced:hover {
                box-shadow:
                    var(--scheme-a-shadow-md),
                    0 4px 12px rgba(0, 0, 0, 0.15);
                border-color: rgba(255, 255, 255, 0.2);
            }

            /* ---- Scheme A: Simple/Eco Mode (节能模式简化) ---- */
            .fxm-capsule.scheme-a.simple {
                box-shadow: none !important;
                border-color: rgba(255, 255, 255, 0.06) !important;
                background: rgba(255, 255, 255, 0.03) !important;
            }

            .fxm-capsule.scheme-a.simple:hover {
                background: rgba(255, 255, 255, 0.06) !important;
                transform: none !important;
                box-shadow: none !important;
            }

            /* ---- Scheme A: Keyframe Animations (关键帧动画) ---- */
            @keyframes scheme-a-pulse-warning {
                0%, 100% {
                    opacity: 1;
                    box-shadow: 0 0 0 0 rgba(245, 158, 11, 0);
                }
                50% {
                    opacity: 0.7;
                    box-shadow: 0 0 0 4px rgba(245, 158, 11, 0.15);
                }
            }

            @keyframes scheme-a-pulse-danger {
                0%, 100% {
                    opacity: 1;
                    box-shadow: 0 0 0 0 rgba(239, 68, 68, 0);
                }
                50% {
                    opacity: 0.8;
                    box-shadow: 0 0 0 6px rgba(239, 68, 68, 0.2);
                }
            }

            /* ---- Scheme A: High Contrast Mode (高对比度模式) ---- */
            @media (prefers-contrast: more) {
                .fxm-capsule.scheme-a {
                    border-color: rgba(255, 255, 255, 0.25);
                }
                .fxm-capsule.scheme-a .fxm-capsule__value,
                .fxm-capsule.scheme-a .fxm-value {
                    font-weight: 700;
                }
                .fxm-capsule.scheme-a .fxm-capsule__unit,
                .fxm-capsule.scheme-a .fxm-unit {
                    opacity: 0.9;
                }
            }

            /* ---- Scheme A: Reduced Motion (减少动画模式) ---- */
            @media (prefers-reduced-motion: reduce) {
                .fxm-capsule.scheme-a,
                .fxm-capsule.scheme-a .fxm-capsule__indicator,
                .fxm-capsule.scheme-a .fxm-indicator,
                .fxm-capsule.scheme-a .fxm-capsule__value,
                .fxm-capsule.scheme-a .fxm-value,
                .fxm-capsule.scheme-a .fxm-capsule__unit,
                .fxm-capsule.scheme-a .fxm-unit,
                .fxm-capsule.scheme-a .fxm-capsule__icon,
                .fxm-capsule.scheme-a .fxm-icon {
                    animation: none !important;
                    transition-duration: 0ms !important;
                }
            }

            /* ---- Scheme A: PRED Disabled State (PRED禁用状态适配) ---- */
            .fxm-capsule.scheme-a.status-pred-disabled {
                opacity: 0.65;
            }

            .fxm-capsule.scheme-a.status-pred-disabled .fxm-capsule__indicator,
            .fxm-capsule.scheme-a.status-pred-disabled .fxm-indicator {
                background: rgba(255, 255, 255, 0.2) !important;
                box-shadow: none !important;
            }

            .fxm-capsule.scheme-a.status-pred-disabled .fxm-capsule__value,
            .fxm-capsule.scheme-a.status-pred-disabled .fxm-value {
                color: #9CA3AF !important;
            }

            .fxm-capsule.scheme-a.status-pred-disabled .fxm-capsule__icon,
            .fxm-capsule.scheme-a.status-pred-disabled .fxm-icon {
                color: #6B7280 !important;
            }

            /* ---- Scheme A: Tray Container Adaptation (底盘容器适配) ---- */
            .fxm-capsule-tray:has(.fxm-capsule.scheme-a) {
                /* 当底盘包含scheme-a胶囊时，使用更简洁的背景 */
                background: linear-gradient(
                    180deg,
                    rgba(20, 20, 25, 0.95) 0%,
                    rgba(15, 15, 20, 0.98) 50%,
                    rgba(10, 10, 15, 0.95) 100%
                );
                border-radius: 24px;
                padding: 8px 12px;
                box-shadow:
                    inset 0 2px 4px rgba(0, 0, 0, 0.4),
                    0 4px 16px rgba(0, 0, 0, 0.3);
            }

            /* Scheme A Tray in enhanced mode */
            .fxm-capsule-tray.enhanced:has(.fxm-capsule.scheme-a) {
                box-shadow:
                    inset 0 2px 4px rgba(0, 0, 0, 0.35),
                    0 4px 16px rgba(0, 0, 0, 0.25),
                    0 0 20px rgba(16, 185, 129, 0.05);
            }

            /* Scheme A Tray in simple mode */
            .fxm-capsule-tray.simple:has(.fxm-capsule.scheme-a) {
                box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.3);
                background: rgba(18, 18, 22, 0.98);
            }

            /* ============================================================================
               SCHEME B: CYBERPUNK TECH (赛博科技未来感) - 完整实现

               视觉特征:
               - 霓虹发光效果 (multi-layer glow)
               - clip-path切角几何造型
               - 扫描线纹理 (scanlines overlay)
               - 高饱和度互补色配色
               - 科技感等宽字体 (Orbitron)
               - 性能降级三级策略
               ============================================================================ */

            /* ---- 方案B: 基础胶囊组件 ---- */
            .fxm-capsule.scheme-b {
                position: relative;
                display: inline-flex;
                align-items: center;
                gap: calc(var(--fxm-capsule-gap, 6px) + 2px);

                height: 28px;
                padding: 7px 16px;

                /* 背景 - 霓虹透明感 */
                background: rgba(0, 212, 255, 0.03);

                /* 边框 + 切角几何造型 */
                border: 1px solid rgba(0, 212, 255, 0.2);
                clip-path: polygon(
                    0 0,
                    calc(100% - 8px) 0,
                    100% 8px,
                    100% 100%,
                    8px 100%,
                    0 calc(100% - 8px)
                );

                /* 字体 - 科技感 Orbitron */
                font-family: 'Orbitron', 'Rajdhani', 'Courier New', monospace;
                font-size: 11px;
                font-weight: 600;
                text-transform: uppercase;
                letter-spacing: 0.08em;
                color: #E0E7FF;

                cursor: default;
                user-select: none;
                white-space: nowrap;
                overflow: hidden;

                /* 过渡效果 */
                transition:
                    background-color 250ms cubic-bezier(0.16, 1, 0.3, 1),
                    border-color 250ms cubic-bezier(0.16, 1, 0.3, 1),
                    box-shadow 250ms cubic-bezier(0.16, 1, 0.3, 1),
                    transform 150ms cubic-bezier(0.16, 1, 0.3, 1);

                /* 性能优化: 仅在需要时合成新层 */
                will-change: transform, box-shadow;

                /* 重置内联样式优先级 */
                min-width: auto !important;
                width: auto !important;
            }

            /* ---- 方案B: 内部光泽叠加层 (::before伪元素) ---- */
            .fxm-capsule.scheme-b::before {
                content: '';
                position: absolute;
                inset: 0;
                background: linear-gradient(
                    135deg,
                    rgba(0, 212, 255, 0.08) 0%,
                    transparent 60%
                );
                pointer-events: none;
                z-index: 0;
            }

            /* ---- 方案B: CRT扫描线纹理层 (::after伪元素) ---- */
            .fxm-capsule.scheme-b::after {
                content: '';
                position: absolute;
                inset: 0;
                background: repeating-linear-gradient(
                    0deg,
                    transparent,
                    transparent 2px,
                    rgba(0, 212, 255, 0.02) 2px,
                    rgba(0, 212, 255, 0.02) 4px
                );
                pointer-events: none;
                z-index: 0;
                opacity: 1;
                transition: opacity 400ms cubic-bezier(0.16, 1, 0.3, 1);
            }

            /* Hover State - 霓虹激活 */
            .fxm-capsule.scheme-b:hover {
                background: rgba(0, 212, 255, 0.08);
                border-color: rgba(0, 212, 255, 0.5);
                box-shadow: 0 0 10px rgba(0, 212, 255, 0.3);
                transform: translateY(-1px);
            }

            /* Hover时扫描线增强 */
            .fxm-capsule.scheme-b:hover::after {
                opacity: 1;
                background: repeating-linear-gradient(
                    0deg,
                    transparent,
                    transparent 2px,
                    rgba(0, 212, 255, 0.04) 2px,
                    rgba(0, 212, 255, 0.04) 4px
                );
            }

            /* Active State */
            .fxm-capsule.scheme-b:active {
                transform: translateY(0) scale(0.98);
            }

            /* Focus Visible - 键盘导航支持 */
            .fxm-capsule.scheme-b:focus-visible {
                outline: 2px solid #00D4FF;
                outline-offset: 2px;
                box-shadow: 0 0 15px rgba(0, 212, 255, 0.4);
            }

            /* ---- 方案B: 状态指示器 (菱形/六边形裁剪) ---- */
            .fxm-capsule.scheme-b .fxm-capsule__indicator,
            .fxm-capsule.scheme-b .fxm-indicator {
                width: 8px;
                height: 8px;
                flex-shrink: 0;
                position: relative;
                z-index: 1;  /* 在扫描线上方 */

                /* 菱形裁剪 - 赛博朋克风格 */
                clip-path: polygon(50% 0%, 100% 50%, 50% 100%, 0% 50%);
                border-radius: 0 !important;  /* 覆盖默认圆形 */

                transition:
                    background-color 250ms cubic-bezier(0.4, 0, 0.2, 1),
                    box-shadow 250ms cubic-bezier(0.4, 0, 0.2, 1),
                    transform 250ms cubic-bezier(0.4, 0, 0.2, 1);
            }

            /* Normal - 绿色发光 */
            .fxm-capsule.scheme-b.status-normal .fxm-capsule__indicator,
            .fxm-capsule.scheme-b.status-normal .fxm-indicator,
            .fxm-capsule.scheme-b .fxm-capsule__indicator--normal,
            .fxm-capsule.scheme-b .fxm-indicator--normal {
                background: #00FF41;
                box-shadow: 0 0 8px rgba(0, 255, 65, 0.6), 0 0 16px rgba(0, 255, 65, 0.3);
            }

            /* Warning - 黄色呼吸动画 */
            .fxm-capsule.scheme-b.status-warning .fxm-capsule__indicator,
            .fxm-capsule.scheme-b.status-warning .fxm-indicator,
            .fxm-capsule.scheme-b .fxm-capsule__indicator--warning,
            .fxm-capsule.scheme-b .fxm-indicator--warning {
                background: #FFFF00;
                box-shadow: 0 0 8px rgba(255, 255, 0, 0.6), 0 0 16px rgba(255, 255, 0, 0.3);
                animation: scheme-b-breath-warning 2s ease-in-out infinite;
            }

            /* Danger - 红色强脉冲 */
            .fxm-capsule.scheme-b.status-danger .fxm-capsule__indicator,
            .fxm-capsule.scheme-b.status-danger .fxm-indicator,
            .fxm-capsule.scheme-b .fxm-capsule__indicator--danger,
            .fxm-capsule.scheme-b .fxm-indicator--danger {
                background: #FF0033;
                box-shadow: 0 0 10px rgba(255, 0, 51, 0.8), 0 0 20px rgba(255, 0, 51, 0.4);
                animation: scheme-b-pulse-danger 1s ease-in-out infinite;
            }

            /* Inactive - 灰色禁用态 */
            .fxm-capsule.scheme-b.status-inactive .fxm-capsule__indicator,
            .fxm-capsule.scheme-b.status-inactive .fxm-indicator,
            .fxm-capsule.scheme-b.status-pred-disabled .fxm-capsule__indicator,
            .fxm-capsule.scheme-b.status-pred-disabled .fxm-indicator {
                background: rgba(255, 255, 255, 0.15);
                box-shadow: none;
                animation: none;
            }

            /* ---- 方案B: 图标 (带霓虹发光滤镜) ---- */
            .fxm-capsule.scheme-b .fxm-capsule__icon,
            .fxm-capsule.scheme-b .fxm-icon {
                width: 16px;
                height: 16px;
                display: flex;
                align-items: center;
                justify-content: center;
                flex-shrink: 0;
                position: relative;
                z-index: 1;

                color: #64748B;
                transition:
                    color 150ms cubic-bezier(0.16, 1, 0.3, 1),
                    filter 250ms cubic-bezier(0.16, 1, 0.3, 1);
                margin-right: 0;  /* 重置原有margin */
            }

            .fxm-capsule.scheme-b .fxm-capsule__icon svg,
            .fxm-capsule.scheme-b .fxm-icon svg {
                width: 100%;
                height: 100%;
                fill: currentColor;
            }

            /* Icon glow on hover parent */
            .fxm-capsule.scheme-b:hover .fxm-capsule__icon,
            .fxm-capsule.scheme-b:hover .fxm-icon {
                color: #00D4FF;
                filter: drop-shadow(0 0 4px rgba(0, 212, 255, 0.5));
            }

            /* Icon colors by status */
            .fxm-capsule.scheme-b.status-normal .fxm-capsule__icon,
            .fxm-capsule.scheme-b.status-normal .fxm-icon { color: #00FF41; }
            .fxm-capsule.scheme-b.status-warning .fxm-capsule__icon,
            .fxm-capsule.scheme-b.status-warning .fxm-icon { color: #FFFF00; }
            .fxm-capsule.scheme-b.status-danger .fxm-capsule__icon,
            .fxm-capsule.scheme-b.status-danger .fxm-icon { color: #FF0033; }

            /* ---- 方案B: 标签 (中文标签) ---- */
            .fxm-capsule.scheme-b .fxm-capsule__label {
                font-family: 'Orbitron', 'Rajdhani', sans-serif;
                font-size: 10px;
                font-weight: 500;
                color: #64748B;
                opacity: 0.7;
                text-transform: uppercase;
                letter-spacing: 0.05em;
                white-space: nowrap;
                text-shadow: none;
            }

            /* ---- 方案B: 数值 (霓虹发光效果) ---- */
            .fxm-capsule.scheme-b .fxm-capsule__value,
            .fxm-capsule.scheme-b .fxm-value {
                font-family: 'JetBrains Mono', 'SF Mono', 'Fira Code', 'Cascadia Code', Consolas, monospace;
                font-size: 16px;
                font-weight: 700;
                line-height: 1;
                color: #00D4FF;

                /* 微弱发光 (不影响阅读) */
                text-shadow: 0 0 8px rgba(0, 212, 255, 0.3);

                /* 等宽数字特性 (对齐) */
                font-feature-settings: 'tnum' on, 'lnum' on;

                position: relative;
                z-index: 1;

                transition:
                    color 250ms cubic-bezier(0.4, 0, 0.2, 1),
                    text-shadow 250ms cubic-bezier(0.4, 0, 0.2, 1);

                min-width: auto !important;
                text-align: left;
            }

            /* Value colors by status */
            .fxm-capsule.scheme-b.status-normal .fxm-capsule__value,
            .fxm-capsule.scheme-b.status-normal .fxm-value {
                color: #00FF41;
                text-shadow: 0 0 8px rgba(0, 255, 65, 0.3);
            }
            .fxm-capsule.scheme-b.status-warning .fxm-capsule__value,
            .fxm-capsule.scheme-b.status-warning .fxm-value {
                color: #FFFF00;
                text-shadow: 0 0 8px rgba(255, 255, 0, 0.3);
            }
            .fxm-capsule.scheme-b.status-danger .fxm-capsule__value,
            .fxm-capsule.scheme-b.status-danger .fxm-value {
                color: #FF0033;
                text-shadow: 0 0 10px rgba(255, 0, 51, 0.4);
            }

            /* ---- 方案B: 单位标签 ---- */
            .fxm-capsule.scheme-b .fxm-capsule__unit,
            .fxm-capsule.scheme-b .fxm-unit {
                font-family: 'Orbitron', 'Rajdhani', sans-serif;
                font-size: 9px;
                font-weight: 500;
                line-height: 1;
                color: #475569;
                margin-left: 2px;
                text-transform: uppercase;
                letter-spacing: 0.1em;
                opacity: 0.7;

                position: relative;
                z-index: 1;

                transition: opacity 150ms cubic-bezier(0.16, 1, 0.3, 1);

                padding-right: 0;  /* 重置padding */
            }

            .fxm-capsule.scheme-b:hover .fxm-capsule__unit,
            .fxm-capsule.scheme-b:hover .fxm-unit {
                opacity: 0.9;
            }

            /* ---- 方案B: Enhanced 增强版变体 ---- */
            .fxm-capsule.scheme-b.enhanced {
                height: 34px !important;
                padding: 9px 20px !important;
                gap: 10px;
                clip-path: polygon(
                    0 0,
                    calc(100% - 10px) 0,
                    100% 10px,
                    100% 100%,
                    10px 100%,
                    0 calc(100% - 10px)
                );
            }

            .fxm-capsule.scheme-b.enhanced .fxm-capsule__indicator,
            .fxm-capsule.scheme-b.enhanced .fxm-indicator {
                width: 10px;
                height: 10px;
            }

            .fxm-capsule.scheme-b.enhanced .fxm-capsule__icon,
            .fxm-capsule.scheme-b.enhanced .fxm-icon {
                width: 20px;
                height: 20px;
            }

            .fxm-capsule.scheme-b.enhanced .fxm-capsule__value,
            .fxm-capsule.scheme-b.enhanced .fxm-value {
                font-size: 18px;
            }

            .fxm-capsule.scheme-b.enhanced .fxm-capsule__unit,
            .fxm-capsule.scheme-b.enhanced .fxm-unit {
                font-size: 11px;
            }

            /* Enhanced mode glow effect */
            .fxm-capsule.scheme-b.enhanced:hover {
                box-shadow:
                    0 0 15px rgba(0, 212, 255, 0.4),
                    0 0 30px rgba(0, 212, 255, 0.2),
                    inset 0 0 20px rgba(0, 212, 255, 0.05);
            }

            /* ---- 方案B: Simple/Eco Mode (节能模式简化) ---- */
            .fxm-capsule.scheme-b.simple {
                box-shadow: none !important;
                background: rgba(0, 20, 40, 0.95) !important;
                border-color: rgba(0, 212, 255, 0.15) !important;
            }

            .fxm-capsule.scheme-b.simple .fxm-capsule__value,
            .fxm-capsule.scheme-b.simple .fxm-value {
                text-shadow: none !important;
            }

            .fxm-capsule.scheme-b.simple .fxm-capsule__indicator,
            .fxm-capsule.scheme-b.simple .fxm-indicator {
                box-shadow: 0 0 4px currentColor !important;
                animation: none !important;
            }

            .fxm-capsule.scheme-b.simple::before,
            .fxm-capsule.scheme-b.simple::after {
                display: none !important;
            }

            .fxm-capsule.scheme-b.simple:hover {
                transform: none !important;
                box-shadow: none !important;
            }

            /* ---- 方案B: 性能降级模式 (FPS < 55) ---- */
            .fxm-capsule.scheme-b.performance-degraded,
            .fxm-capsule.scheme-b.low-fps {
                /* 移除扫描线纹理以节省性能 */
            }

            .fxm-capsule.scheme-b.performance-degraded::after,
            .fxm-capsule.scheme-b.low-fps::after {
                display: none !important;
            }

            /* 简化发光效果 */
            .fxm-capsule.scheme-b.performance-degraded,
            .fxm-capsule.scheme-b.low-fps {
                box-shadow: none !important;
            }

            .fxm-capsule.scheme-b.performance-degraded .fxm-capsule__value,
            .fxm-capsule.scheme-b.low-fps .fxm-capsule__value,
            .fxm-capsule.scheme-b.performance-degraded .fxm-value,
            .fxm-capsule.scheme-b.low-fps .fxm-value {
                text-shadow: none !important;
            }

            .fxm-capsule.scheme-b.performance-degraded .fxm-capsule__indicator,
            .fxm-capsule.scheme-b.low-fps .fxm-capsule__indicator,
            .fxm-capsule.scheme-b.performance-degraded .fxm-indicator,
            .fxm-capsule.scheme-b.low-fps .fxm-indicator {
                box-shadow: 0 0 4px currentColor !important;
                animation: none !important;
            }

            /* 极简模式 (FPS < 30 或 battery saver) */
            .fxm-capsule.scheme-b.ultra-low-performance {
                clip-path: none !important;
                border-radius: 8px !important;
                background: rgba(255, 255, 255, 0.05) !important;
                border: 1px solid rgba(255, 255, 255, 0.1) !important;
            }

            .fxm-capsule.scheme-b.ultra-low-performance::before,
            .fxm-capsule.scheme-b.ultra-low-performance::after {
                display: none !important;
            }

            /* ---- 方案B: 关键帧动画 ---- */
            @keyframes scheme-b-breath-warning {
                0%, 100% {
                    transform: scale(1) rotate(0deg);
                    box-shadow: 0 0 8px rgba(255, 255, 0, 0.6), 0 0 16px rgba(255, 255, 0, 0.3);
                }
                50% {
                    transform: scale(1.15) rotate(45deg);
                    box-shadow: 0 0 12px rgba(255, 255, 0, 0.8), 0 0 24px rgba(255, 255, 0, 0.4);
                }
            }

            @keyframes scheme-b-pulse-danger {
                0%, 100% {
                    transform: scale(1);
                    box-shadow: 0 0 10px rgba(255, 0, 51, 0.8), 0 0 20px rgba(255, 0, 51, 0.4);
                }
                50% {
                    transform: scale(1.2);
                    box-shadow: 0 0 15px rgba(255, 0, 51, 1), 0 0 30px rgba(255, 0, 51, 0.5), 0 0 45px rgba(255, 0, 51, 0.2);
                }
            }

            /* Glitch effect (可选，仅用于特殊场合) */
            @keyframes scheme-b-glitch {
                0%, 90%, 100% {
                    transform: translate(0);
                    filter: hue-rotate(0deg);
                }
                92% {
                    transform: translate(-2px, 1px);
                    filter: hue-rotate(90deg);
                }
                94% {
                    transform: translate(2px, -1px);
                    filter: hue-rotate(180deg);
                }
                96% {
                    transform: translate(-1px, 2px);
                    filter: hue-rotate(270deg);
                }
                98% {
                    transform: translate(1px, -2px);
                    filter: hue-rotate(360deg);
                }
            }

            /* ---- 方案B: Reduced Motion 支持 ---- */
            @media (prefers-reduced-motion: reduce) {
                .fxm-capsule.scheme-b,
                .fxm-capsule.scheme-b *,
                .fxm-capsule.scheme-b::before,
                .fxm-capsule.scheme-b::after {
                    animation: none !important;
                    transition-duration: 0ms !important;
                }
            }

            /* ---- 方案B: PRED Disabled State (PRED禁用状态适配) ---- */
            .fxm-capsule.scheme-b.status-pred-disabled {
                opacity: 0.65;
            }

            .fxm-capsule.scheme-b.status-pred-disabled .fxm-capsule__value,
            .fxm-capsule.scheme-b.status-pred-disabled .fxm-value {
                color: #64748B !important;
                text-shadow: none !important;
            }

            .fxm-capsule.scheme-b.status-pred-disabled .fxm-capsule__icon,
            .fxm-capsule.scheme-b.status-pred-disabled .fxm-icon {
                color: #475569 !important;
                filter: drop-shadow(0 0 2px rgba(71, 85, 105, 0.3)) !important;
            }

            /* ---- 方案B: 5种主题色霓虹变体 ---- */

            /* Theme: Cyan (默认) - 电光蓝 (#00ffff) */
            [data-theme="cyan"] .fxm-capsule.scheme-b,
            .fxm-capsule.scheme-b.theme-cyan {
                --scheme-b-neon-primary: #00ffff;
                --scheme-b-neon-secondary: #0088ff;
                background: rgba(0, 255, 255, 0.03);
                border-color: rgba(0, 255, 255, 0.2);
            }
            [data-theme="cyan"] .fxm-capsule.scheme-b::before,
            .fxm-capsule.scheme-b.theme-cyan::before {
                background: linear-gradient(135deg, rgba(0, 255, 255, 0.08) 0%, transparent 60%);
            }
            [data-theme="cyan"] .fxm-capsule.scheme-b .fxm-capsule__value,
            [data-theme="cyan"] .fxm-capsule.scheme-b .fxm-value,
            .fxm-capsule.scheme-b.theme-cyan .fxm-capsule__value,
            .fxm-capsule.scheme-b.theme-cyan .fxm-value {
                color: #00ffff;
                text-shadow: 0 0 8px rgba(0, 255, 255, 0.3);
            }
            [data-theme="cyan"] .fxm-capsule.scheme-b:hover,
            .fxm-capsule.scheme-b.theme-cyan:hover {
                background: rgba(0, 255, 255, 0.08);
                border-color: rgba(0, 255, 255, 0.5);
                box-shadow: 0 0 10px rgba(0, 255, 255, 0.3);
            }
            [data-theme="cyan"] .fxm-capsule.scheme-b:hover::after,
            .fxm-capsule.scheme-b.theme-cyan:hover::after {
                background: repeating-linear-gradient(
                    0deg,
                    transparent,
                    transparent 2px,
                    rgba(0, 255, 255, 0.04) 2px,
                    rgba(0, 255, 255, 0.04) 4px
                );
            }

            /* Theme: Violet/Purple - 霓虹紫 (#bf00ff) */
            [data-theme="violet"] .fxm-capsule.scheme-b,
            .fxm-capsule.scheme-b.theme-violet {
                --scheme-b-neon-primary: #bf00ff;
                --scheme-b-neon-secondary: #8b00ff;
                background: rgba(191, 0, 255, 0.03);
                border-color: rgba(191, 0, 255, 0.2);
            }
            [data-theme="violet"] .fxm-capsule.scheme-b::before,
            .fxm-capsule.scheme-b.theme-violet::before {
                background: linear-gradient(135deg, rgba(191, 0, 255, 0.08) 0%, transparent 60%);
            }
            [data-theme="violet"] .fxm-capsule.scheme-b .fxm-capsule__value,
            [data-theme="violet"] .fxm-capsule.scheme-b .fxm-value,
            .fxm-capsule.scheme-b.theme-violet .fxm-capsule__value,
            .fxm-capsule.scheme-b.theme-violet .fxm-value {
                color: #bf00ff;
                text-shadow: 0 0 8px rgba(191, 0, 255, 0.3);
            }
            [data-theme="violet"] .fxm-capsule.scheme-b:hover,
            .fxm-capsule.scheme-b.theme-violet:hover {
                background: rgba(191, 0, 255, 0.08);
                border-color: rgba(191, 0, 255, 0.5);
                box-shadow: 0 0 10px rgba(191, 0, 255, 0.3);
            }
            [data-theme="violet"] .fxm-capsule.scheme-b:hover::after,
            .fxm-capsule.scheme-b.theme-violet:hover::after {
                background: repeating-linear-gradient(
                    0deg,
                    transparent,
                    transparent 2px,
                    rgba(191, 0, 255, 0.04) 2px,
                    rgba(191, 0, 255, 0.04) 4px
                );
            }

            /* Theme: Emerald/Green - 矩阵绿 (#00ff88) */
            [data-theme="emerald"] .fxm-capsule.scheme-b,
            .fxm-capsule.scheme-b.theme-emerald {
                --scheme-b-neon-primary: #00ff88;
                --scheme-b-neon-secondary: #00cc33;
                background: rgba(0, 255, 136, 0.03);
                border-color: rgba(0, 255, 136, 0.2);
            }
            [data-theme="emerald"] .fxm-capsule.scheme-b::before,
            .fxm-capsule.scheme-b.theme-emerald::before {
                background: linear-gradient(135deg, rgba(0, 255, 136, 0.08) 0%, transparent 60%);
            }
            [data-theme="emerald"] .fxm-capsule.scheme-b .fxm-capsule__value,
            [data-theme="emerald"] .fxm-capsule.scheme-b .fxm-value,
            .fxm-capsule.scheme-b.theme-emerald .fxm-capsule__value,
            .fxm-capsule.scheme-b.theme-emerald .fxm-value {
                color: #00ff88;
                text-shadow: 0 0 8px rgba(0, 255, 136, 0.3);
            }
            [data-theme="emerald"] .fxm-capsule.scheme-b:hover,
            .fxm-capsule.scheme-b.theme-emerald:hover {
                background: rgba(0, 255, 136, 0.08);
                border-color: rgba(0, 255, 136, 0.5);
                box-shadow: 0 0 10px rgba(0, 255, 136, 0.3);
            }
            [data-theme="emerald"] .fxm-capsule.scheme-b:hover::after,
            .fxm-capsule.scheme-b.theme-emerald:hover::after {
                background: repeating-linear-gradient(
                    0deg,
                    transparent,
                    transparent 2px,
                    rgba(0, 255, 136, 0.04) 2px,
                    rgba(0, 255, 136, 0.04) 4px
                );
            }

            /* Theme: Amber/Orange - 琥珀橙 (#ffaa00) */
            [data-theme="amber"] .fxm-capsule.scheme-b,
            .fxm-capsule.scheme-b.theme-amber {
                --scheme-b-neon-primary: #ffaa00;
                --scheme-b-neon-secondary: #ff8800;
                background: rgba(255, 170, 0, 0.03);
                border-color: rgba(255, 170, 0, 0.2);
            }
            [data-theme="amber"] .fxm-capsule.scheme-b::before,
            .fxm-capsule.scheme-b.theme-amber::before {
                background: linear-gradient(135deg, rgba(255, 170, 0, 0.08) 0%, transparent 60%);
            }
            [data-theme="amber"] .fxm-capsule.scheme-b .fxm-capsule__value,
            [data-theme="amber"] .fxm-capsule.scheme-b .fxm-value,
            .fxm-capsule.scheme-b.theme-amber .fxm-capsule__value,
            .fxm-capsule.scheme-b.theme-amber .fxm-value {
                color: #ffaa00;
                text-shadow: 0 0 8px rgba(255, 170, 0, 0.3);
            }
            [data-theme="amber"] .fxm-capsule.scheme-b:hover,
            .fxm-capsule.scheme-b.theme-amber:hover {
                background: rgba(255, 170, 0, 0.08);
                border-color: rgba(255, 170, 0, 0.5);
                box-shadow: 0 0 10px rgba(255, 170, 0, 0.3);
            }
            [data-theme="amber"] .fxm-capsule.scheme-b:hover::after,
            .fxm-capsule.scheme-b.theme-amber:hover::after {
                background: repeating-linear-gradient(
                    0deg,
                    transparent,
                    transparent 2px,
                    rgba(255, 170, 0, 0.04) 2px,
                    rgba(255, 170, 0, 0.04) 4px
                );
            }

            /* Theme: Sky/Blue - 天空蓝 (#00aaff) */
            [data-theme="sky"] .fxm-capsule.scheme-b,
            .fxm-capsule.scheme-b.theme-sky {
                --scheme-b-neon-primary: #00aaff;
                --scheme-b-neon-secondary: #0088cc;
                background: rgba(0, 170, 255, 0.03);
                border-color: rgba(0, 170, 255, 0.2);
            }
            [data-theme="sky"] .fxm-capsule.scheme-b::before,
            .fxm-capsule.scheme-b.theme-sky::before {
                background: linear-gradient(135deg, rgba(0, 170, 255, 0.08) 0%, transparent 60%);
            }
            [data-theme="sky"] .fxm-capsule.scheme-b .fxm-capsule__value,
            [data-theme="sky"] .fxm-capsule.scheme-b .fxm-value,
            .fxm-capsule.scheme-b.theme-sky .fxm-capsule__value,
            .fxm-capsule.scheme-b.theme-sky .fxm-value {
                color: #00aaff;
                text-shadow: 0 0 8px rgba(0, 170, 255, 0.3);
            }
            [data-theme="sky"] .fxm-capsule.scheme-b:hover,
            .fxm-capsule.scheme-b.theme-sky:hover {
                background: rgba(0, 170, 255, 0.08);
                border-color: rgba(0, 170, 255, 0.5);
                box-shadow: 0 0 10px rgba(0, 170, 255, 0.3);
            }
            [data-theme="sky"] .fxm-capsule.scheme-b:hover::after,
            .fxm-capsule.scheme-b.theme-sky:hover::after {
                background: repeating-linear-gradient(
                    0deg,
                    transparent,
                    transparent 2px,
                    rgba(0, 170, 255, 0.04) 2px,
                    rgba(0, 170, 255, 0.04) 4px
                );
            }

            /* ---- Scheme B: Tray Container Adaptation (底盘容器适配) ---- */
            .fxm-capsule-tray:has(.fxm-capsule.scheme-b) {
                /* 当底盘包含scheme-b胶囊时，使用深空黑背景 + 霓虹边框 */
                background: linear-gradient(
                    180deg,
                    rgba(0, 5, 15, 0.95) 0%,
                    rgba(5, 5, 12, 0.98) 50%,
                    rgba(0, 3, 10, 0.95) 100%
                );
                border-radius: 22px;
                padding: 10px 16px;
                box-shadow:
                    inset 0 3px 10px rgba(0, 0, 0, 0.8),
                    0 0 30px rgba(0, 212, 255, 0.1),
                    0 8px 25px rgba(0, 0, 0, 0.6);
                border: 1px solid rgba(0, 212, 255, 0.15);
            }

            /* Scheme B Tray in enhanced mode */
            .fxm-capsule-tray.enhanced:has(.fxm-capsule.scheme-b) {
                box-shadow:
                    inset 0 3px 10px rgba(0, 0, 0, 0.75),
                    0 0 40px rgba(0, 212, 255, 0.15),
                    0 8px 30px rgba(0, 0, 0, 0.55);
            }

            /* Scheme B Tray in simple mode */
            .fxm-capsule-tray.simple:has(.fxm-capsule.scheme-b) {
                box-shadow: inset 0 2px 6px rgba(0, 0, 0, 0.6);
                background: rgba(0, 5, 15, 0.98);
                border-color: rgba(0, 212, 255, 0.08);
            }

            /* ============================================================================
               SCHEME C: GLASSMORPHISM REFINED (精致玻璃态) - 完整实现
               
               灵感来源:
               - macOS Big Sur/Tahoe widgets (Frosted glass, Liquid Glass)
               - iOS 17+ widgets (Material system)
               - Windows 11 Acrylic/Mica materials
               - Vercel dashboard (Subtle depth)
               - Linear App 2025 (Custom frosted glass)
               
               设计特征:
               - backdrop-filter毛玻璃模糊效果 ★核心特性★
               - 多层半透明叠加
               - 半透明白色边框 (1px solid rgba(255,255,255,0.15))
               - 柔和的内阴影和高光 (inset highlight)
               - 渐变状态色彩 (苹果语义色)
               - 物理感阴影 (多光源模拟)
               
               兼容性策略 (三层降级):
               - Layer 1: @supports(backdrop-filter) 标准检测
               - Layer 2: -webkit- 前缀检测 (旧版Safari/iOS)
               - Layer 3: .no-glass / .glass-disabled 类 (JS显式禁用)
               ============================================================================ */

            /* ---- Scheme C: Color Tokens (玻璃态CSS变量) ---- */
            :root {
                --scheme-c-glass-bg-light:     rgba(255, 255, 255, 0.08);
                --scheme-c-glass-bg-dark:      rgba(255, 255, 255, 0.05);
                --scheme-c-glass-bg-hover:     rgba(255, 255, 255, 0.12);
                --scheme-c-glass-bg-solid:     rgba(30, 30, 30, 0.92);
                
                --scheme-c-glass-border:       1px solid rgba(255, 255, 255, 0.15);
                --scheme-c-glass-border-hover: 1px solid rgba(255, 255, 255, 0.25);
                --scheme-c-glass-border-light: 1px solid rgba(255, 255, 255, 0.08);
                
                --scheme-c-blur-standard:      blur(20px);
                --scheme-c-blur-heavy:         blur(30px) saturate(180%);
                --scheme-c-blur-ultra:         blur(40px) saturate(200%);
                
                /* 苹果语义色 (iOS/macOS标准) */
                --scheme-c-color-success:      #34C759;
                --scheme-c-color-warning:      #FF9500;
                --scheme-c-color-danger:       #FF3B30;
                --scheme-c-color-info:         #007AFF;
                
                /* 渐变变体 (用于状态指示) */
                --scheme-c-gradient-success:   linear-gradient(135deg, #34C759 0%, #30D158 100%);
                --scheme-c-gradient-warning:   linear-gradient(135deg, #FF9500 0%, #FFCC00 100%);
                --scheme-c-gradient-danger:    linear-gradient(135deg, #FF3B30 0%, #FF453A 100%);
                
                /* 文字颜色 */
                --scheme-c-text-primary:      #FFFFFF;
                --scheme-c-text-secondary:    rgba(255, 255, 255, 0.6);
                --scheme-c-text-muted:        rgba(255, 255, 255, 0.4);
                
                /* 物理感阴影 (模拟多光源) */
                --scheme-c-shadow-elevation:   
                    0 8px 32px rgba(0, 0, 0, 0.2),
                    0 2px 8px rgba(0, 0, 0, 0.1);
                --scheme-c-shadow-hover:        
                    0 12px 40px rgba(0, 0, 0, 0.3),
                    0 4px 12px rgba(0, 0, 0, 0.15);
                    
                /* 内高光 (顶部反光) */
                --scheme-c-inner-highlight:    inset 0 1px 0 rgba(255, 255, 255, 0.1);
                --scheme-c-inner-highlight-strong: inset 0 1px 0 rgba(255, 255, 255, 0.15);
                
                /* 胶囊特定 */
                --scheme-c-capsule-radius:     24px;  /* 大圆角胶囊 */
            }

            /* ---- Scheme C: Capsule Component (基础样式) ---- */
            .fxm-capsule.scheme-c {
                position: relative;
                display: inline-flex;
                align-items: center;
                gap: var(--fxm-capsule-gap, 6px);
                
                /* 尺寸 - 大圆角胶囊 (36px高度) */
                height: 36px;
                padding: 8px 18px;
                
                /* 玻璃背景 + 模糊 ★核心特性★ */
                background: var(--scheme-c-glass-bg-dark);
                backdrop-filter: var(--scheme-c-blur-standard);
                -webkit-backdrop-filter: var(--scheme-c-blur-standard);  /* Safari前缀 */
                
                /* 边框 - 半透明白色 */
                border: var(--scheme-c-glass-border);
                border-radius: var(--scheme-c-capsule-radius);
                
                /* 内高光 + 物理感阴影 */
                box-shadow: 
                    var(--scheme-c-inner-highlight),
                    var(--scheme-c-shadow-elevation);
                
                /* 字体 - 系统字体优先，清晰可读 */
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                font-size: 13px;
                font-weight: 650;  /* 介于semibold和bold之间 */
                letter-spacing: -0.015em;
                color: var(--scheme-c-text-primary);
                
                cursor: default;
                user-select: none;
                white-space: nowrap;
                overflow: hidden;
                
                /* 物理感过渡 (Apple-style spring out) */
                transition: 
                    background-color 250ms cubic-bezier(0.16, 1, 0.3, 1),
                    border-color 250ms cubic-bezier(0.16, 1, 0.3, 1),
                    box-shadow 250ms cubic-bezier(0.16, 1, 0.3, 1),
                    transform 250ms cubic-bezier(0.16, 1, 0.3, 1),
                    backdrop-filter 250ms cubic-bezier(0.16, 1, 0.3, 1);
                
                /* 性能优化: will-change将在JS中动态控制 */
                will-change: auto;
            }

            /* ---- Scheme C: Hover State - 提升感 + 增强模糊 ---- */
            .fxm-capsule.scheme-c:hover {
                background: var(--scheme-c-glass-bg-hover);
                border-color: rgba(255, 255, 255, 0.25);
                box-shadow: 
                    var(--scheme-c-inner-highlight-strong),
                    var(--scheme-c-shadow-hover);
                transform: translateY(-2px);
                
                /* Hover时增强backdrop-filter模糊度 */
                backdrop-filter: var(--scheme-c-blur-heavy);
                -webkit-backdrop-filter: var(--scheme-c-blur-heavy);
            }

            /* ---- Scheme C: Active/Pressed State ---- */
            .fxm-capsule.scheme-c:active {
                transform: translateY(0) scale(0.98);
                box-shadow: 
                    var(--scheme-c-inner-highlight),
                    0 4px 16px rgba(0, 0, 0, 0.15);
            }

            /* ---- Scheme C: Focus Visible (键盘导航可访问性) ---- */
            .fxm-capsule.scheme-c:focus-visible {
                outline: 2px solid var(--scheme-c-color-info);
                outline-offset: 2px;
                box-shadow: 
                    0 0 0 4px rgba(0, 122, 255, 0.2),
                    var(--scheme-c-inner-highlight);
            }

            /* ---- Scheme C: Status Indicator (圆形，柔和投影) ---- */
            .fxm-capsule.scheme-c .fxm-indicator,
            .fxm-capsule.scheme-c .fxm-capsule__indicator {
                width: 8px;
                height: 8px;
                border-radius: 50%;
                flex-shrink: 0;
                
                /* 柔和物理感阴影 */
                box-shadow: 0 2px 6px rgba(0, 0, 0, 0.25);
                
                transition: 
                    background-color 250ms cubic-bezier(0.4, 0, 0.2, 1),
                    box-shadow 250ms cubic-bezier(0.4, 0, 0.2, 1),
                    transform 250ms cubic-bezier(0.4, 0, 0.2, 1);
            }

            /* Normal (<60%) - 绿色渐变 + 柔和发光 */
            .fxm-capsule.scheme-c.status-normal .fxm-indicator,
            .fxm-capsule.scheme-c.status-normal .fxm-capsule__indicator,
            .fxm-capsule.scheme-c .fxm-indicator--normal,
            .fxm-capsule.scheme-c .fxm-capsule__indicator--normal {
                background: var(--scheme-c-gradient-success);
                box-shadow: 
                    0 2px 8px rgba(52, 199, 89, 0.4),
                    0 0 12px rgba(52, 199, 89, 0.2);
            }

            /* Warning (60-80%) - 橙色渐变 + 呼吸动画 */
            .fxm-capsule.scheme-c.status-warning .fxm-indicator,
            .fxm-capsule.scheme-c.status-warning .fxm-capsule__indicator,
            .fxm-capsule.scheme-c .fxm-indicator--warning,
            .fxm-capsule.scheme-c .fxm-capsule__indicator--warning {
                background: var(--scheme-c-gradient-warning);
                box-shadow: 
                    0 2px 8px rgba(255, 149, 0, 0.4),
                    0 0 12px rgba(255, 149, 0, 0.2);
                animation: scheme-c-breathe 2.5s ease-in-out infinite;
            }

            /* Danger (>80%) - 红色渐变 + 明显脉冲 */
            .fxm-capsule.scheme-c.status-danger .fxm-indicator,
            .fxm-capsule.scheme-c.status-danger .fxm-capsule__indicator,
            .fxm-capsule.scheme-c .fxm-indicator--danger,
            .fxm-capsule.scheme-c .fxm-capsule__indicator--danger {
                background: var(--scheme-c-gradient-danger);
                box-shadow: 
                    0 2px 10px rgba(255, 59, 48, 0.5),
                    0 0 16px rgba(255, 59, 48, 0.25);
                animation: scheme-c-pulse 2s ease-in-out infinite;
            }

            /* Inactive/Disabled */
            .fxm-capsule.scheme-c.status-inactive .fxm-indicator,
            .fxm-capsule.scheme-c.status-inactive .fxm-capsule__indicator,
            .fxm-capsule.scheme-c .fxm-indicator--inactive,
            .fxm-capsule.scheme-c .fxm-capsule__indicator--inactive {
                background: rgba(255, 255, 255, 0.2);
                box-shadow: none;
                animation: none;
            }

            /* ---- Scheme C: Icon (图标) ---- */
            .fxm-capsule.scheme-c .fxm-icon,
            .fxm-capsule.scheme-c .fxm-capsule__icon {
                width: 14px;
                height: 14px;
                display: flex;
                align-items: center;
                justify-content: center;
                flex-shrink: 0;
                color: var(--scheme-c-text-secondary);
                margin-right: 0;  /* 重置原有margin */
                transition: color 150ms cubic-bezier(0.16, 1, 0.3, 1);
                filter: none;  /* 移除drop-shadow以保持玻璃态清爽 */
            }

            .fxm-capsule.scheme-c .fxm-icon svg,
            .fxm-capsule.scheme-c .fxm-capsule__icon svg {
                width: 100%;
                height: 100%;
                fill: currentColor;
            }

            /* Hover时图标变亮 */
            .fxm-capsule.scheme-c:hover .fxm-icon,
            .fxm-capsule.scheme-c:hover .fxm-capsule__icon {
                color: var(--scheme-c-text-primary);
            }

            /* 图标颜色随状态变化 (苹果语义色) */
            .fxm-capsule.scheme-c.status-normal .fxm-icon,
            .fxm-capsule.scheme-c.status-normal .fxm-capsule__icon { 
                color: var(--scheme-c-color-success); 
            }
            .fxm-capsule.scheme-c.status-warning .fxm-icon,
            .fxm-capsule.scheme-c.status-warning .fxm-capsule__icon { 
                color: var(--scheme-c-color-warning); 
            }
            .fxm-capsule.scheme-c.status-danger .fxm-icon,
            .fxm-capsule.scheme-c.status-danger .fxm-capsule__icon { 
                color: var(--scheme-c-color-danger); 
            }

            /* ---- Scheme C: Value (纯净白色，最高可读性) ---- */
            .fxm-capsule.scheme-c .fxm-value,
            .fxm-capsule.scheme-c .fxm-capsule__value {
                font-family: 'JetBrains Mono', 'SF Mono', Consolas, monospace;
                font-size: 16px;
                font-weight: 700;
                line-height: 1;
                color: var(--scheme-c-text-primary);
                
                /* 无text-shadow保证最佳可读性（玻璃态背景上文字必须清晰） */
                text-shadow: none;
                
                min-width: auto !important;
                text-align: left;
                font-feature-settings: 'tnum' on, 'lnum' on;
                transition: color 250ms cubic-bezier(0.4, 0, 0.2, 1);
            }

            /* ---- Scheme C: Label (中文标签) ---- */
            .fxm-capsule.scheme-c .fxm-capsule__label {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                font-size: 11px;
                font-weight: 500;
                color: var(--scheme-c-text-secondary);
                opacity: 1;  /* 重置opacity */
                text-shadow: none;  /* 移除text-shadow */
                white-space: nowrap;
                letter-spacing: 0.02em;
            }

            /* ---- Scheme C: Unit (单位) ---- */
            .fxm-capsule.scheme-c .fxm-unit,
            .fxm-capsule.scheme-c .fxm-capsule__unit {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                font-size: 11px;
                font-weight: 500;
                line-height: 1;
                color: var(--scheme-c-text-secondary);
                margin-left: 1px;
                padding-right: 0;  /* 重置padding */
                text-transform: uppercase;
                letter-spacing: 0.05em;
                opacity: 1;  /* 重置opacity */
                text-shadow: none;
                white-space: nowrap;
                transition: color 150ms cubic-bezier(0.16, 1, 0.3, 1);
            }

            /* ---- Scheme C: Enhanced Variant (更大更突出) ---- */
            .fxm-capsule.scheme-c.enhanced {
                height: 40px !important;
                padding: 10px 24px !important;
                gap: 10px;
                
                /* 更强的模糊效果 */
                backdrop-filter: var(--scheme-c-blur-heavy);
                -webkit-backdrop-filter: var(--scheme-c-blur-heavy);
            }

            .fxm-capsule.scheme-c.enhanced .fxm-indicator,
            .fxm-capsule.scheme-c.enhanced .fxm-capsule__indicator {
                width: 10px;
                height: 10px;
            }

            .fxm-capsule.scheme-c.enhanced .fxm-icon,
            .fxm-capsule.scheme-c.enhanced .fxm-capsule__icon {
                width: 18px;
                height: 18px;
            }

            .fxm-capsule.scheme-c.enhanced .fxm-value,
            .fxm-capsule.scheme-c.enhanced .fxm-capsule__value {
                font-size: 18px;
            }

            .fxm-capsule.scheme-c.enhanced .fxm-unit,
            .fxm-capsule.scheme-c.enhanced .fxm-capsule__unit {
                font-size: 12px;
            }

            /* ---- Scheme C: Simple/Eco Mode (节能模式简化) ---- */
            .fxm-capsule.scheme-c.simple {
                /* 移除毛玻璃效果以节省性能 */
                backdrop-filter: none !important;
                -webkit-backdrop-filter: none !important;
                background: rgba(30, 30, 30, 0.95) !important;
                box-shadow: 
                    0 4px 16px rgba(0, 0, 0, 0.25) !important;
                border-color: rgba(255, 255, 255, 0.10) !important;
            }

            .fxm-capsule.scheme-c.simple:hover {
                transform: none !important;
                background: rgba(35, 35, 45, 0.97) !important;
            }

            /* ====================================================================
               SCHEME C: 三层兼容性降级策略 (Compatibility Fallback)
               这是方案C的最大挑战！必须确保跨浏览器一致性。
               ==================================================================== */

            /**
             * Layer 1: @supports 检测 backdrop-filter 标准支持
             * 不支持时使用半透明纯色背景作为优雅降级
             * 目标浏览器: IE11, 旧版Firefox (<103), 旧版Edge
             */
            @supports not (backdrop-filter: blur(1px)) {
                .fxm-capsule.scheme-c {
                    /* 降级为半透明深色纯色背景 */
                    background: var(--scheme-c-glass-bg-solid);
                    border-color: rgba(255, 255, 255, 0.12);
                    
                    /* 移除所有backdrop-filter相关属性 */
                    backdrop-filter: none;
                    -webkit-backdrop-filter: none;
                }
                
                .fxm-capsule.scheme-c:hover {
                    background: rgba(30, 30, 30, 0.95);
                }
                
                /* Enhanced变体的降级 */
                .fxm-capsule.scheme-c.enhanced {
                    background: rgba(25, 25, 35, 0.96);
                }
            }

            /**
             * Layer 2: -webkit- 前缀检测 (旧版Safari/iOS < 9)
             * 针对不支持标准属性但支持webkit前缀的WebKit内核
             * 双重降级策略: 使用半透明渐变背景模拟玻璃质感
             */
            @supports not (-webkit-backdrop-filter: blur(1px)) and (not (backdrop-filter: blur(1px))) {
                .fxm-capsule.scheme-c {
                    /* 使用渐变模拟玻璃质感（比纯色更有层次） */
                    background: 
                        linear-gradient(
                            135deg,
                            rgba(255, 255, 255, 0.06) 0%,
                            rgba(255, 255, 255, 0.03) 100%
                        );
                    box-shadow: 
                        var(--scheme-c-inner-highlight),
                        0 4px 16px rgba(0, 0, 0, 0.25);
                    
                    /* 强制移除所有backdrop-filter */
                    backdrop-filter: none !important;
                    -webkit-backdrop-filter: none !important;
                }
                
                .fxm-capsule.scheme-c:hover {
                    background: 
                        linear-gradient(
                            135deg,
                            rgba(255, 255, 255, 0.10) 0%,
                            rgba(255, 255, 255, 0.06) 100%
                        );
                }
            }

            /**
             * Layer 3: 显式禁用类 (JavaScript动态控制)
             * 当检测到以下情况时通过JS添加此类：
             * - FPS < 30 (低帧率影响用户体验)
             * - GPU使用率过高 (避免卡顿)
             * - 用户手动禁用 (设置选项)
             * - 移动端电池节省模式
             * - 性能监控检测到问题
             */
            .fxm-capsule.scheme-c.no-glass,
            .fxm-capsule.scheme-c.glass-disabled,
            .fxm-capsule.scheme-c.performance-degraded {
                /* 强制使用不透明背景 */
                background: rgba(30, 30, 30, 0.95) !important;
                
                /* 移除所有毛玻璃效果 */
                backdrop-filter: none !important;
                -webkit-backdrop-filter: none !important;
                
                /* 弱化边框 */
                border-color: rgba(255, 255, 255, 0.12) !important;
                
                /* 简化阴影 */
                box-shadow: 
                    0 4px 16px rgba(0, 0, 0, 0.25) !important;
                
                /* 重置will-change以释放内存 */
                will-change: auto !important;
            }

            /* ---- Scheme C: Light Mode Support (浅色模式适配) ---- */
            /* 通过父容器 [data-theme="light"] 或 .light-mode 触发 */
            [data-theme="light"] .fxm-capsule.scheme-c,
            .light-mode .fxm-capsule.scheme-c {
                background: var(--scheme-c-glass-bg-light);
                border-color: rgba(0, 0, 0, 0.08);
                color: #1c1c1e;  /* 深色文字确保可读性 */
                box-shadow: 
                    inset 0 1px 0 rgba(255, 255, 255, 0.8),
                    0 4px 16px rgba(0, 0, 0, 0.08);
            }

            [data-theme="light"] .fxm-capsule.scheme-c .fxm-value,
            [data-theme="light"] .fxm-capsule.scheme-c .fxm-capsule__value,
            .light-mode .fxm-capsule.scheme-c .fxm-value,
            .light-mode .fxm-capsule.scheme-c .fxm-capsule__value {
                color: #1c1c1e;
            }

            [data-theme="light"] .fxm-capsule.scheme-c .fxm-unit,
            [data-theme="light"] .fxm-capsule.scheme-c .fxm-capsule__unit,
            .light-mode .fxm-capsule.scheme-c .fxm-unit,
            .light-mode .fxm-capsule.scheme-c .fxm-capsule__unit {
                color: rgba(0, 0, 0, 0.5);
            }

            [data-theme="light"] .fxm-capsule.scheme-c .fxm-icon,
            [data-theme="light"] .fxm-capsule.scheme-c .fxm-capsule__icon,
            .light-mode .fxm-capsule.scheme-c .fxm-icon,
            .light-mode .fxm-capsule.scheme-c .fxm-capsule__icon {
                color: rgba(0, 0, 0, 0.45);
            }

            [data-theme="light"] .fxm-capsule.scheme-c .fxm-capsule__label,
            .light-mode .fxm-capsule.scheme-c .fxm-capsule__label {
                color: rgba(0, 0, 0, 0.55);
            }

            /* ---- Scheme C: Keyframes (关键帧动画) ---- */
            @keyframes scheme-c-breathe {
                0%, 100% { 
                    transform: scale(1);
                    box-shadow: 
                        0 2px 8px rgba(255, 149, 0, 0.4),
                        0 0 12px rgba(255, 149, 0, 0.2);
                }
                50% { 
                    transform: scale(1.12);
                    box-shadow: 
                        0 2px 12px rgba(255, 149, 0, 0.6),
                        0 0 20px rgba(255, 149, 0, 0.3);
                }
            }

            @keyframes scheme-c-pulse {
                0%, 100% { 
                    transform: scale(1);
                    box-shadow: 
                        0 2px 10px rgba(255, 59, 48, 0.5),
                        0 0 16px rgba(255, 59, 48, 0.25);
                }
                50% { 
                    transform: scale(1.15);
                    box-shadow: 
                        0 2px 14px rgba(255, 59, 48, 0.7),
                        0 0 24px rgba(255, 59, 48, 0.35),
                        0 0 32px rgba(255, 59, 48, 0.15);
                }
            }

            /* ---- Scheme C: High Contrast Mode (高对比度无障碍模式) ---- */
            @media (prefers-contrast: more) {
                .fxm-capsule.scheme-c {
                    border-color: rgba(255, 255, 255, 0.3);
                    background: rgba(30, 30, 30, 0.98);
                }
                
                .fxm-capsule.scheme-c .fxm-value,
                .fxm-capsule.scheme-c .fxm-capsule__value {
                    font-weight: 700;
                }
            }

            /* ---- Scheme C: Reduced Motion (减少动画 - 无障碍) ---- */
            @media (prefers-reduced-motion: reduce) {
                .fxm-capsule.scheme-c,
                .fxm-capsule.scheme-c .fxm-indicator,
                .fxm-capsule.scheme-c .fxm-capsule__indicator,
                .fxm-capsule.scheme-c .fxm-value,
                .fxm-capsule.scheme-c .fxm-capsule__value,
                .fxm-capsule.scheme-c .fxm-unit,
                .fxm-capsule.scheme-c .fxm-capsule__unit {
                    animation: none !important;
                    transition-duration: 0ms !important;
                }
            }

            /* ---- Scheme C: PRED Disabled State (PRED禁用状态适配) ---- */
            .fxm-capsule.scheme-c.status-pred-disabled {
                opacity: 0.65;
            }

            .fxm-capsule.scheme-c.status-pred-disabled .fxm-capsule__indicator,
            .fxm-capsule.scheme-c.status-pred-disabled .fxm-indicator {
                background: rgba(255, 255, 255, 0.2) !important;
                box-shadow: none !important;
            }

            .fxm-capsule.scheme-c.status-pred-disabled .fxm-capsule__value,
            .fxm-capsule.scheme-c.status-pred-disabled .fxm-value {
                color: rgba(255, 255, 255, 0.45) !important;
            }

            .fxm-capsule.scheme-c.status-pred-disabled .fxm-capsule__icon,
            .fxm-capsule.scheme-c.status-pred-disabled .fxm-icon {
                color: rgba(255, 255, 255, 0.3) !important;
            }

            /* ---- Scheme C: Tray Container Adaptation (底盘容器适配) ---- */
            .fxm-capsule-tray:has(.fxm-capsule.scheme-c) {
                /* 当底盘包含方案C胶囊时，使用更透明的背景以展示毛玻璃效果 */
                background: linear-gradient(
                    180deg,
                    rgba(26, 30, 46, 0.85) 0%,
                    rgba(20, 24, 36, 0.90) 50%,
                    rgba(16, 20, 31, 0.92) 100%
                );
                border-radius: 24px;
                padding: 10px 16px;
                box-shadow:
                    inset 0 3px 8px rgba(0, 0, 0, 0.6),
                    0 6px 20px rgba(0, 0, 0, 0.45);
            }

            /* Scheme C Tray in enhanced mode */
            .fxm-capsule-tray.enhanced:has(.fxm-capsule.scheme-c) {
                box-shadow:
                    inset 0 2px 6px rgba(0, 0, 0, 0.5),
                    0 4px 16px rgba(0, 0, 0, 0.35),
                    0 0 30px rgba(255, 255, 255, 0.03);  /* 微弱环境光反射 */
            }

            /* Scheme C Tray in simple mode */
            .fxm-capsule-tray.simple:has(.fxm-capsule.scheme-c) {
                box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.4);
                background: rgba(18, 18, 24, 0.96);
            }

            /* ============================================================
               方案切换按钮组 (Scheme Switcher A/B/C)
               ============================================================ */
            
            /* 按钮组容器 */
            .fxm-scheme-switcher {
                display: flex !important;
                align-items: center !important;
                gap: 4px !important;
                padding: 3px !important;
                background: rgba(0, 0, 0, 0.35) !important;
                border-radius: 8px !important;
                border: 1px solid rgba(255, 255, 255, 0.12) !important;
                transition: all 0.25s ease !important;
            }

            .fxm-scheme-switcher:hover {
                border-color: rgba(255, 255, 255, 0.2) !important;
                background: rgba(0, 0, 0, 0.45) !important;
            }

            /* 单个方案按钮 */
            .fxm-scheme-btn {
                width: 24px !important;
                height: 24px !important;
                min-width: 24px !important;
                min-height: 24px !important;
                border-radius: 6px !important;
                border: 2px solid transparent !important;
                background: rgba(255, 255, 255, 0.08) !important;
                color: #ffffff !important;
                font-size: 11px !important;
                font-weight: 700 !important;
                cursor: pointer !important;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
                transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1) !important;
                outline: none !important;
                user-select: none !important;
                position: relative !important;
                overflow: hidden !important;
                padding: 0 !important;
                margin: 0 !important;
            }

            /* 按钮标签 */
            .fxm-scheme-btn__label {
                line-height: 1 !important;
                pointer-events: none !important;
                font-size: inherit !important;
                font-weight: inherit !important;
            }

            /* 默认态 - 鼠标悬停 */
            .fxm-scheme-btn:hover:not(.active) {
                background: rgba(255, 255, 255, 0.18) !important;
                transform: scale(1.08) !important;
                border-color: rgba(255, 255, 255, 0.15) !important;
            }

            /* 选中态 - 高亮显示 */
            .fxm-scheme-btn.active {
                border-color: var(--fxm-primary-color, #00ffff) !important;
                background: rgba(0, 255, 255, 0.2) !important;
                box-shadow: 
                    0 0 10px rgba(0, 255, 255, 0.35),
                    inset 0 1px 2px rgba(255, 255, 255, 0.1) !important;
                transform: scale(1) !important;
            }

            .fxm-scheme-btn.active:hover {
                background: rgba(0, 255, 255, 0.28) !important;
                box-shadow: 
                    0 0 14px rgba(0, 255, 255, 0.45),
                    inset 0 1px 2px rgba(255, 255, 255, 0.15) !important;
            }

            /* 点击反馈 */
            .fxm-scheme-btn:active:not(.active) {
                transform: scale(0.95) !important;
                background: rgba(255, 255, 255, 0.22) !important;
            }

            .fxm-scheme-btn.active:active {
                transform: scale(0.96) !important;
            }

            /* 焦点可见性 (无障碍) */
            .fxm-scheme-btn:focus-visible {
                outline: 2px solid var(--fxm-primary-color, #00ffff) !important;
                outline-offset: 2px !important;
            }

            /* 方案按钮特殊着色 (可选增强) */
            .fxm-scheme-btn[data-scheme="scheme-a"].active {
                border-color: #34C759 !important;  /* 绿色-极简 */
                background: rgba(52, 199, 89, 0.2) !important;
                box-shadow: 0 0 10px rgba(52, 199, 89, 0.35), inset 0 1px 2px rgba(255, 255, 255, 0.1) !important;
            }

            .fxm-scheme-btn[data-scheme="scheme-b"].active {
                border-color: #00ffff !important;  /* 青色-科技 */
                background: rgba(0, 255, 255, 0.2) !important;
                box-shadow: 0 0 10px rgba(0, 255, 255, 0.35), inset 0 1px 2px rgba(255, 255, 255, 0.1) !important;
            }

            .fxm-scheme-btn[data-scheme="scheme-c"].active {
                border-color: #bf00ff !important;  /* 紫色-玻璃 */
                background: rgba(191, 0, 255, 0.2) !important;
                box-shadow: 0 0 10px rgba(191, 0, 255, 0.35), inset 0 1px 2px rgba(255, 255, 255, 0.1) !important;
            }
        `;
        document.head.appendChild(style);

        console.log('[飞雪监测器] 🎨 CSS注入完成: 方案A/B/C 全部集成');
        console.log('   ✓ 方案A: Minimalist Pro (极简主义专业版)');
        console.log('   ✓ 方案B: Cyberpunk Tech (赛博科技未来感)');
        console.log('   ✓ 方案C: Glassmorphism Refined (精致玻璃态)');
        console.log('   方案C特性: backdrop-filter毛玻璃 + 三层兼容性降级 + Light模式');
    }

    // ============================================================
    // FPS监控和自动降级系统 (方案B专用)
    // ============================================================

    /**
     * 方案B性能监控器 - 实时FPS检测与自动降级
     *
     * **核心功能**:
     * - 使用requestAnimationFrame精确测量实际帧率
     * - 三级性能策略:
     *   1. 正常模式 (FPS >= 55): 全部特效（扫描线、发光、动画）
     *   2. 降级模式 (30 <= FPS < 55): 移除扫描线、简化glow
     *   3. 极简模式 (FPS < 30): 移除clip-path、移除所有伪元素
     * - 智能恢复: FPS稳定后自动升级特效级别
     * - 节流机制: 避免频繁DOM操作导致性能抖动
     *
     * **设计原则**:
     * - 非侵入式: 只影响.scheme-b元素
     * - 渐进式降级: 不会突然完全失效
     * - 可观测性: 控制台日志便于调试
     */
    let schemeB_PerformanceMonitor = {
        frames: 0,
        lastTime: performance.now(),
        currentFPS: 60,
        rafId: null,
        isRunning: false,

        /**
         * 启动FPS监控循环
         * @param {boolean} forceRestart - 是否强制重启（用于重新初始化）
         */
        start: function(forceRestart) {
            if (this.isRunning && !forceRestart) {
                console.log('[方案B性能监控] ✓ 监控已在运行');
                return;
            }

            if (this.rafId) {
                cancelAnimationFrame(this.rafId);
            }

            this.frames = 0;
            this.lastTime = performance.now();
            this.isRunning = true;

            var self = this;
            this.rafId = requestAnimationFrame(function measureLoop(currentTime) {
                if (!self.isRunning) return;

                self.frames++;

                // 每秒计算一次FPS
                if (currentTime >= self.lastTime + 1000) {
                    self.currentFPS = Math.round((self.frames * 1000) / (currentTime - self.lastTime));

                    // 应用性能降级策略
                    self.applyPerformanceLevel(self.currentFPS);

                    // 重置计数器
                    self.frames = 0;
                    self.lastTime = currentTime;
                }

                self.rafId = requestAnimationFrame(measureLoop);
            });

            console.log('[方案B性能监控] 🚀 已启动 | 初始FPS: ~' + this.currentFPS);
        },

        /**
         * 停止FPS监控
         */
        stop: function() {
            this.isRunning = false;
            if (this.rafId) {
                cancelAnimationFrame(this.rafId);
                this.rafId = null;
            }
            console.log('[方案B性能监控] ⏹️ 已停止');
        },

        /**
         * 根据FPS值应用对应的性能级别
         * @param {number} fps - 当前帧率
         */
        applyPerformanceLevel: function(fps) {
            // 查找所有方案B胶囊
            var schemeBCapsules = document.querySelectorAll('.fxm-capsule.scheme-b');

            if (schemeBCapsules.length === 0) return;  // 无方案B元素时跳过

            var newLevel, levelDescription;

            if (fps >= 55) {
                // ===== 正常模式: 全部特效 =====
                newLevel = 'full';
                levelDescription = '全特效';

                schemeBCapsules.forEach(function(el) {
                    el.classList.remove('performance-degraded', 'low-fps', 'ultra-low-performance');
                });
            } else if (fps >= 30) {
                // ===== 降级模式: 移除扫描线、简化glow =====
                newLevel = 'degraded';
                levelDescription = '简化(无扫描线)';

                schemeBCapsules.forEach(function(el) {
                    el.classList.remove('ultra-low-performance');
                    el.classList.add('performance-degraded', 'low-fps');
                });
            } else {
                // ===== 极简模式: 移除clip-path、所有伪元素 =====
                newLevel = 'minimal';
                levelDescription = '极简(扁平化)';

                schemeBCapsules.forEach(function(el) {
                    el.classList.add('ultra-low-performance');
                    el.classList.remove('performance-degraded', 'low-fps');  // ultra-low已包含degraded效果
                });
            }

            // 仅在级别变化或每5秒输出一次日志（避免刷屏）
            if (!this._lastLevel || this._lastLevel !== newLevel || !this._lastLogTime || Date.now() - this._lastLogTime > 5000) {
                console.log(
                    '[方案B性能监控] 📊 FPS: ' + fps +
                    ' | 级别: ' + levelDescription +
                    ' (' + newLevel + ')' +
                    ' | 胶囊数: ' + schemeBCapsules.length
                );
                this._lastLevel = newLevel;
                this._lastLogTime = Date.now();
            }
        },

        /**
         * 手动触发一次性能检测（用于测试）
         * @returns {number} 当前估算的FPS值
         */
        checkNow: function() {
            return this.currentFPS;
        },

        /**
         * 销毁监控器（释放资源）
         */
        destroy: function() {
            this.stop();
            this.frames = 0;
            this.lastTime = 0;
            this.currentFPS = 0;
            this._lastLevel = null;
            this._lastLogTime = null;

            // 清理可能残留的降级类
            var schemeBCapsules = document.querySelectorAll('.fxm-capsule.scheme-b');
            schemeBCapsules.forEach(function(el) {
                el.classList.remove('performance-degraded', 'low-fps', 'ultra-low-performance');
            });

            console.log('[方案B性能监控] 🔴 已销毁并清理资源');
        }
    };

    /**
     * 加载Orbitron字体 (方案B专用科技感字体)
     *
     * 使用异步加载，不阻塞页面渲染。
     * 提供多个fallback字体确保可用性。
     */
    function loadOrbitronFont() {
        // 检查字体是否已加载
        if (document.fonts && document.fonts.check('12px "Orbitron"')) {
            console.log('[方案B字体] ✓ Orbitron 字体已就绪');
            return Promise.resolve();
        }

        // 尝试从Google Fonts加载
        var fontUrl = 'https://fonts.googleapis.com/css2?family=Orbitron:wght@400;500;600;700;800;900&display=swap';

        return new Promise(function(resolve, reject) {
            var link = document.createElement('link');
            link.rel = 'stylesheet';
            link.href = fontUrl;
            link.crossOrigin = 'anonymous';
            link.onload = function() {
                console.log('[方案B字体] ✅ Orbitron 字体加载成功 (Google Fonts)');
                resolve();
            };
            link.onerror = function() {
                // Google Fonts加载失败时使用系统等宽字体作为fallback
                console.warn('[方案B字体] ⚠️ Google Fonts加载失败，使用系统字体fallback (Rajdhani/Courier New)');
                resolve();  // 不阻塞，使用CSS中定义的fallback字体链
            };

            document.head.appendChild(link);
        });
    }

    // ============================================================
    // 主初始化函数
    // ============================================================
    async function init() {
        console.log(`[飞雪监测器] ✅ v${CONFIG.version} 初始化中...`);

        try {
            // 1. 创建顶部菜单栏
            const bar = createTopMenuBar();
            console.log('[飞雪监测器] ✅ 顶部菜单栏已创建');

            // 2. 设置事件委托（替代直接绑定）
            setupEventDelegation(bar);
            console.log('[飞雪监测器] ✅ 事件委托已设置');

            // 3. 创建悬浮面板
            createHoverPanel();
            console.log('[飞雪监测器] ✅ 悬浮面板已创建');

            // 3.5 恢复上次保存的主题（必须在面板创建之后）
            restoreSavedTheme();

            // 3.55 恢复性能/节能模式偏好（Task 4）
            loadUserPreferences();

            // 3.551 应用性能模式到UI（延迟执行确保DOM已就绪）
            setTimeout(() => {
                // 更新模式切换按钮的外观以匹配恢复的状态
                const modeToggle = document.getElementById('fxm-mode-toggle');
                if (modeToggle) {
                    if (performanceMode) {
                        modeToggle.innerHTML = '⚡';
                        modeToggle.style.background = 'radial-gradient(circle, #00ff41 0%, #00cc33 100%)';
                        modeToggle.style.boxShadow = '0 0 10px rgba(0, 255, 65, 0.5)';
                        modeToggle.title = '性能模式：开启所有视觉效果';
                    } else {
                        modeToggle.innerHTML = '🍃';
                        modeToggle.style.background = 'radial-gradient(circle, #888888 0%, #666666 100%)';
                        modeToggle.style.boxShadow = 'none';
                        modeToggle.title = '节能模式：简化视觉效果以节省资源';
                    }
                }

                // 应用性能模式设置（毛玻璃、阴影、动画等）
                applyPerformanceMode(performanceMode);

                console.log(`[飞雪监测器] ✅ 性能模式已应用: ${performanceMode ? '⚡ 性能' : '🍃 节能'}`);
            }, 100);

            // 3.56 恢复用户保存的方案偏好 (scheme-a / scheme-b / scheme-c)
            restoreSavedScheme();

            // 3.565 同步方案切换按钮状态（确保按钮高亮与当前方案一致）
            setTimeout(() => {
                updateSchemeButtonStates(CONFIG.currentScheme);
                console.log(`[飞雪] 🎨 方案切换按钮已同步: ${CONFIG.currentScheme} (${(CONFIG.schemeLabels[CONFIG.currentScheme] != null ? CONFIG.schemeLabels[CONFIG.currentScheme].title : undefined) || ''})`);
            }, 150);  /* 延迟150ms等待DOM和按钮组创建完成 */

            // 3.57 初始化方案C (Glassmorphism) 兼容性检测和性能优化
            // 必须在DOM创建完成后执行，检测backdrop-filter支持情况
            setTimeout(() => {
                const schemeCResult = initSchemeCCompatibility();
                
                // 如果当前使用的是方案C，输出详细的兼容性报告
                if (CONFIG.currentScheme === 'scheme-c') {
                    console.log('[飞雪监测器] 🎨 方案C Glassmorphism 已激活');
                    console.log(`   backdrop-filter支持: ${schemeCResult.supported ? '✅ 完整' : '⚠️ 降级模式'}`);
                    console.log(`   检测方法: ${schemeCResult.method}`);
                    console.log(`   浏览器: ${schemeCResult.browserInfo}`);
                }
            }, 150);  /* 延迟150ms确保所有胶囊DOM已创建 */

            // 3.58 如果当前是方案B，启动FPS监控和加载字体（延迟确保DOM就绪）
            setTimeout(() => {
                if (CONFIG.currentScheme === 'scheme-b') {
                    // 启动FPS性能监控
                    if (typeof schemeB_PerformanceMonitor !== 'undefined') {
                        schemeB_PerformanceMonitor.start();
                        console.log('[飞雪监测器] ✅ 方案B FPS性能监控已启动');
                    }

                    // 加载Orbitron科技感字体
                    if (typeof loadOrbitronFont !== 'undefined') {
                        loadOrbitronFont().then(() => {
                            console.log('[飞雪监测器] ✅ Orbitron 字体已为方案B加载');
                        });
                    }
                }
            }, 200);

            // 3.6 恢复 PRED 预测开关偏好（Task 5）
            restorePredTogglePreference();

            // 根据恢复的状态初始化预测引擎UI
            if (predEnabled) {
                // 如果用户之前开启了预测，延迟启动引擎（确保DOM已就绪）
                setTimeout(() => {
                    togglePredictionEngine(true);
                }, 100);
            }

            // 4. 启动定时数据更新（使用可管理的定时器）
            startDataCollection();
            console.log('[飞雪监测器] ✅ 数据采集已启动');

            // 5. 立即执行一次数据更新（使用统一数据源）
            const initialData = await getUnifiedSystemData();
            updateCapsules(initialData);

            // 6. 导出全局API（包含destroy方法）
            window.FeixueMonitor = {
                version: CONFIG.version,
                currentScheme: CONFIG.currentScheme,  // 暴露当前方案
                show: () => {
                    const p = document.getElementById('fxm-hover-panel');
                    if(p) { p.style.display = 'block'; panelVisible = true; }
                },
                hide: () => {
                    const p = document.getElementById('fxm-hover-panel');
                    if(p) { p.style.display = 'none'; panelVisible = false; }
                },
                toggle: togglePanel,
                getData: getUnifiedSystemData,  // ← 使用统一数据源函数
                refresh: async () => {
                    // 强制刷新：清除缓存后重新获取
                    cachedSystemData = null;
                    lastUnifiedDataTime = 0;

                    const unifiedData = await getUnifiedSystemData();
                    updateCapsules(unifiedData);

                    if (panelVisible) {
                        updatePanelData(unifiedData);
                    }

                    console.log('[飞雪监测器] 🔄 手动刷新完成 - 胶囊与面板数据已同步更新');
                },
                /**
                 * 切换UI方案 (scheme-a ↔ scheme-b)
                 * @param {string} scheme - 目标方案 ('scheme-a' 或 'scheme-b')
                 * @returns {boolean} 是否切换成功
                 */
                switchScheme: function(scheme) {
                    return switchUIScheme(scheme);
                },
                /**
                 * 获取当前FPS（仅方案B有效）
                 * @returns {number|null} 当前FPS值或null（如果监控未启动）
                 */
                getFPS: function() {
                    if (typeof schemeB_PerformanceMonitor !== 'undefined' && schemeB_PerformanceMonitor.isRunning) {
                        return schemeB_PerformanceMonitor.currentFPS;
                    }
                    return null;
                },
                destroy: function() {
                    // 停止数据采集定时器
                    stopDataCollection();

                    // 销毁方案B FPS监控器（如果存在）
                    if (typeof schemeB_PerformanceMonitor !== 'undefined') {
                        schemeB_PerformanceMonitor.destroy();
                    }

                    // 移除DOM元素
                    const menuBar = document.getElementById('fxm-top-menu-bar');
                    if (menuBar) menuBar.remove();

                    const panel = document.getElementById('fxm-hover-panel');
                    if (panel) panel.remove();

                    const styles = document.getElementById('fxm-styles');
                    if (styles) styles.remove();

                    // 清理全局引用和缓存
                    delete window.FeixueMonitor;
                    delete window.fxmSwitchScheme;  // 清理方案切换全局函数
                    cachedSystemData = null;
                    lastUnifiedDataTime = 0;
                    panelVisible = false;

                    console.log('[飞雪监测器] 🔴 监测器已销毁 (含方案B资源清理)');
                }
            };

            console.log('[飞雪监测器] 🎉 初始化完成！');
            console.log('[飞雪监测器] 💡 可用方法:');
            console.log('   - FeixueMonitor.show() / hide() / toggle()');
            console.log('   - FeixueMonitor.getData() / refresh()');
            console.log('   - FeixueMonitor.switchScheme("scheme-a"|"scheme-b"|"scheme-c") - 切换UI方案');
            console.log('   - FeixueMonitor.getFPS() - 获取当前帧率(方案B)');
            console.log('   - FeixueMonitor.destroy() - 完全销毁并清理资源');
            console.log('   - fxmSwitchScheme("scheme-b") - 全局快捷方式');
            console.log(`[飞雪监测器] 🎨 当前视觉方案: ${CONFIG.currentScheme} (${(CONFIG.schemeLabels[CONFIG.currentScheme] != null ? CONFIG.schemeLabels[CONFIG.currentScheme].title : undefined) || ''})`);
            console.log('[飞雪监测器] \u{1F504} 方案切换: 点击面板内 A/B/C 按钮或调用 API');

        } catch (error) {
            console.error('[飞雪监测器] ❌ 初始化失败:', error);
        }
    }

    // ============================================================
    // 启动入口
    // ============================================================
    
    // 等待DOM就绪
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        // DOM已经就绪，延迟一小段时间确保ComfyUI环境准备好
        setTimeout(init, 500);
    }

})();
