// ===================== Theme Management =====================
function initTheme() {
    const savedTheme = localStorage.getItem('theme') || 'light';
    document.documentElement.setAttribute('data-theme', savedTheme);
}

function toggleTheme() {
    const currentTheme = document.documentElement.getAttribute('data-theme');
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', newTheme);
    localStorage.setItem('theme', newTheme);
}

// ===================== Mobile Menu =====================
function toggleMobileMenu() {
    const mobileNav = document.getElementById('mobileNav');
    if (mobileNav) {
        mobileNav.classList.toggle('active');
    }
}

// ===================== Chatbot =====================
let chatbotOpen = false;

function toggleChatbot() {
    chatbotOpen = !chatbotOpen;
    const container = document.getElementById('chatbotContainer');
    const fab = document.querySelector('.chatbot-fab');
    
    if (container) {
        if (chatbotOpen) {
            container.classList.add('active');
            fab.classList.add('active');
        } else {
            container.classList.remove('active');
            fab.classList.remove('active');
        }
    }
}

function openChatbot() {
    chatbotOpen = true;
    const container = document.getElementById('chatbotContainer');
    const fab = document.querySelector('.chatbot-fab');
    
    if (container) {
        container.classList.add('active');
        fab.classList.add('active');
    }
}

function closeChatbot() {
    chatbotOpen = false;
    const container = document.getElementById('chatbotContainer');
    const fab = document.querySelector('.chatbot-fab');
    
    if (container) {
        container.classList.remove('active');
        fab.classList.remove('active');
    }
}

function addMessage(content, isUser = false) {
    const messagesContainer = document.getElementById('chatMessages');
    if (!messagesContainer) return;
    
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${isUser ? 'message-user' : 'message-bot'}`;
    
    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';
    contentDiv.textContent = content;
    
    messageDiv.appendChild(contentDiv);
    messagesContainer.appendChild(messageDiv);
    
    // Scroll to bottom
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

function addLoadingMessage() {
    const messagesContainer = document.getElementById('chatMessages');
    if (!messagesContainer) return;
    
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message message-bot';
    messageDiv.id = 'loading-message';
    
    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';
    contentDiv.textContent = '...';
    
    messageDiv.appendChild(contentDiv);
    messagesContainer.appendChild(messageDiv);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

function removeLoadingMessage() {
    const loadingMessage = document.getElementById('loading-message');
    if (loadingMessage) {
        loadingMessage.remove();
    }
}

async function sendMessage() {
    const input = document.getElementById('chatInput');
    if (!input) return;
    
    const message = input.value.trim();
    if (!message) return;
    
    // Add user message
    addMessage(message, true);
    input.value = '';
    
    // Add loading indicator
    addLoadingMessage();
    
    try {
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ message: message }),
        });
        
        const data = await response.json();
        
        // Remove loading indicator
        removeLoadingMessage();
        
        if (data.error) {
            addMessage('عذراً، حدث خطأ: ' + data.error, false);
        } else {
            addMessage(data.reply || 'لم أستطع فهم السؤال', false);
        }
    } catch (error) {
        removeLoadingMessage();
        addMessage('عذراً، حدث خطأ في الاتصال. يرجى المحاولة مرة أخرى.', false);
        console.error('Chat error:', error);
    }
}

function handleChatKeyPress(event) {
    if (event.key === 'Enter') {
        sendMessage();
    }
}

// ===================== Flash Messages Auto-dismiss =====================
function initFlashMessages() {
    const flashMessages = document.querySelectorAll('.flash');
    flashMessages.forEach(flash => {
        setTimeout(() => {
            flash.style.animation = 'slide-out-right 0.3s ease';
            setTimeout(() => {
                flash.remove();
            }, 300);
        }, 5000);
    });
}

// ===================== Form Validation =====================
function validateForm(formId) {
    const form = document.getElementById(formId);
    if (!form) return true;
    
    const requiredFields = form.querySelectorAll('[required]');
    let isValid = true;
    
    requiredFields.forEach(field => {
        if (!field.value.trim()) {
            isValid = false;
            field.style.borderColor = 'rgb(239, 68, 68)';
        } else {
            field.style.borderColor = '';
        }
    });
    
    return isValid;
}

// ===================== Smooth Scroll =====================
function smoothScroll(target) {
    const element = document.querySelector(target);
    if (element) {
        element.scrollIntoView({
            behavior: 'smooth',
            block: 'start'
        });
    }
}

// ===================== Initialize on Load =====================
document.addEventListener('DOMContentLoaded', function() {
    // Initialize theme
    initTheme();
    
    // Initialize flash messages
    initFlashMessages();
    
    // Add animation classes to elements as they come into view
    const observerOptions = {
        threshold: 0.1,
        rootMargin: '0px 0px -50px 0px'
    };
    
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('fade-in');
                observer.unobserve(entry.target);
            }
        });
    }, observerOptions);
    
    // Observe elements with animation classes
    document.querySelectorAll('.feature-card, .request-card').forEach(el => {
        observer.observe(el);
    });
});

// ===================== Utility Functions =====================
function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleDateString('ar-SA', {
        year: 'numeric',
        month: 'long',
        day: 'numeric'
    });
}

function formatTime(dateString) {
    const date = new Date(dateString);
    return date.toLocaleTimeString('ar-SA', {
        hour: '2-digit',
        minute: '2-digit'
    });
}

// ===================== Export Functions =====================
window.toggleTheme = toggleTheme;
window.toggleMobileMenu = toggleMobileMenu;
window.toggleChatbot = toggleChatbot;
window.openChatbot = openChatbot;
window.closeChatbot = closeChatbot;
window.sendMessage = sendMessage;
window.handleChatKeyPress = handleChatKeyPress;
window.smoothScroll = smoothScroll;
