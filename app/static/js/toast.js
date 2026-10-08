// Toast Notification System for Library System

class Toast {
    constructor() {
        this.container = null;
        this.init();
    }

    init() {
        // Create toast container if it doesn't exist
        if (!document.getElementById('toast-container')) {
            this.container = document.createElement('div');
            this.container.id = 'toast-container';
            this.container.className = 'fixed right-4 space-y-3';
            this.container.style.cssText = `
                max-width: 400px;
                z-index: 2147483647 !important;
                top: 90px !important;
                pointer-events: none;
                position: fixed !important;
            `;
            document.body.appendChild(this.container);
        } else {
            this.container = document.getElementById('toast-container');
        }
    }

    show(message, type = 'info', duration = 4000) {
        const toast = this.createToast(message, type);
        this.container.appendChild(toast);

        // Trigger animation
        setTimeout(() => {
            toast.classList.add('toast-show');
        }, 10);

        // Auto remove
        setTimeout(() => {
            this.remove(toast);
        }, duration);

        return toast;
    }

    createToast(message, type) {
        const toast = document.createElement('div');
        toast.className = `toast toast-${type} flex items-start gap-3 p-4 rounded-xl shadow-lg transform transition-all duration-300 translate-x-full opacity-0`;
        toast.style.pointerEvents = 'auto'; // Toast có thể click được

        const config = this.getTypeConfig(type);
        toast.style.background = config.background;
        toast.style.border = `1px solid ${config.border}`;

        toast.innerHTML = `
            <div class="flex-shrink-0 w-10 h-10 rounded-lg flex items-center justify-center" style="background: ${config.iconBg}">
                ${config.icon}
            </div>
            <div class="flex-1 pt-1">
                <h4 class="font-semibold text-sm mb-1" style="color: ${config.titleColor}">${config.title}</h4>
                <p class="toast-message text-sm" style="color: ${config.textColor}; white-space: pre-line"></p>
            </div>
            <button class="flex-shrink-0 text-gray-400 hover:text-gray-600 transition-colors mt-1" onclick="this.closest('.toast').remove()">
                <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                </svg>
            </button>
        `;
        // Gán nội dung bằng textContent để không thể chèn HTML/JS (chống XSS)
        toast.querySelector('.toast-message').textContent = String(message);

        return toast;
    }

    getTypeConfig(type) {
        const configs = {
            success: {
                title: 'Thành công!',
                background: 'linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%)',
                border: '#a7f3d0',
                iconBg: 'linear-gradient(135deg, #10b981 0%, #059669 100%)',
                titleColor: '#065f46',
                textColor: '#047857',
                icon: `<svg class="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
                </svg>`
            },
            error: {
                title: 'Lỗi!',
                background: 'linear-gradient(135deg, #fef2f2 0%, #fee2e2 100%)',
                border: '#fecaca',
                iconBg: 'linear-gradient(135deg, #ef4444 0%, #dc2626 100%)',
                titleColor: '#991b1b',
                textColor: '#b91c1c',
                icon: `<svg class="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                </svg>`
            },
            warning: {
                title: 'Cảnh báo!',
                background: 'linear-gradient(135deg, #fffbeb 0%, #fef3c7 100%)',
                border: '#fde68a',
                iconBg: 'linear-gradient(135deg, #f59e0b 0%, #d97706 100%)',
                titleColor: '#92400e',
                textColor: '#b45309',
                icon: `<svg class="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/>
                </svg>`
            },
            info: {
                title: 'Thông tin',
                background: 'linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%)',
                border: '#bfdbfe',
                iconBg: 'linear-gradient(135deg, #3b82f6 0%, #2563eb 100%)',
                titleColor: '#1e40af',
                textColor: '#1d4ed8',
                icon: `<svg class="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
                </svg>`
            }
        };

        return configs[type] || configs.info;
    }

    remove(toast) {
        toast.classList.remove('toast-show');
        toast.classList.add('toast-hide');
        setTimeout(() => {
            if (toast.parentNode) {
                toast.parentNode.removeChild(toast);
            }
        }, 300);
    }

    success(message, duration) {
        return this.show(message, 'success', duration);
    }

    error(message, duration) {
        return this.show(message, 'error', duration);
    }

    warning(message, duration) {
        return this.show(message, 'warning', duration);
    }

    info(message, duration) {
        return this.show(message, 'info', duration);
    }
}

// Initialize toast instance after DOM is ready
let toast;

// Khởi tạo toast khi DOM đã sẵn sàng
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() {
        toast = new Toast();
    });
} else {
    // DOM đã sẵn sàng
    toast = new Toast();
}

// Add CSS for animations
const style = document.createElement('style');
style.textContent = `
    .toast {
        min-width: 320px;
        backdrop-filter: blur(10px);
    }

    .toast-show {
        transform: translateX(0) !important;
        opacity: 1 !important;
    }

    .toast-hide {
        transform: translateX(120%) !important;
        opacity: 0 !important;
    }

    @media (max-width: 640px) {
        #toast-container {
            left: 1rem;
            right: 1rem;
            max-width: calc(100% - 2rem) !important;
        }

        .toast {
            min-width: 100%;
        }
    }
`;
document.head.appendChild(style);
