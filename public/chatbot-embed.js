/**
 * Chatbot Embed Script - Premium Responsive Version
 * Usage: <script src="http://your-domain/chatbot-embed.js" data-chatbot-id="YOUR_ID" data-public-token="YOUR_TOKEN"></script>
 */
(function() {
    // Get config from script tag
    const scriptTag = document.currentScript || document.querySelector('script[src*="chatbot-embed.js"]');
    
    // Auto-detect API Base URL based on script src
    let autoApiUrl = window.location.origin;
    if (scriptTag && scriptTag.src) {
        try {
            const urlObj = new URL(scriptTag.src);
            autoApiUrl = urlObj.origin;
        } catch (e) {
            console.error('Failed to parse script source URL:', e);
        }
    }

    // Create a unique localStorage key based on chatbotId
    const STORAGE_KEY = `chatbot_session_${scriptTag?.getAttribute('data-chatbot-id') || ''}`;
    
    const CONFIG = {
        chatbotId: scriptTag?.getAttribute('data-chatbot-id') || '',
        publicToken: scriptTag?.getAttribute('data-public-token') || '',
        apiBaseUrl: scriptTag?.getAttribute('data-api-url') || autoApiUrl,
        position: scriptTag?.getAttribute('data-position') || 'bottom-right',
        themeColor: scriptTag?.getAttribute('data-theme-color') || '#4f46e5', // Sleek Indigo
        botName: scriptTag?.getAttribute('data-bot-name') || 'AI Assistant',
        avatarUrl: scriptTag?.getAttribute('data-avatar-url') || '',
        workspaceId: null,
        workflowWebhookUrl: null,
        suggestions: [],
        sessionId: localStorage.getItem(STORAGE_KEY) || null
    };
    
    let input, sendBtn, messagesDiv;
    let isSending = false; // Prevent duplicate requests
    
    // Helper function to ensure URL is absolute
    function ensureAbsoluteUrl(url, baseUrl) {
        if (!url) return baseUrl + '/chatbot_logo.jpeg';
        try {
            new URL(url);
            return url; // Already absolute
        } catch (e) {
            // Relative URL, prepend baseUrl
            return baseUrl + (url.startsWith('/') ? '' : '/') + url;
        }
    }

    // Helper function to add cache-busting parameter to URL
    function addCacheBusting(url) {
        if (!url) return url;
        const timestamp = Date.now();
        try {
            const urlObj = new URL(url);
            urlObj.searchParams.set('t', timestamp.toString());
            return urlObj.toString();
        } catch (e) {
            // If it's not a valid URL, just append the parameter
            const separator = url.includes('?') ? '&' : '?';
            return url + separator + 't=' + timestamp;
        }
    }
    
    // Default avatar URL (chatbot_logo.jpeg) - use API base URL
    const defaultAvatarUrl = CONFIG.apiBaseUrl + '/chatbot_logo.jpeg';
    
    // Ensure avatar URL is absolute
    CONFIG.avatarUrl = ensureAbsoluteUrl(CONFIG.avatarUrl, CONFIG.apiBaseUrl);
    

    if (!CONFIG.chatbotId || !CONFIG.publicToken) {
        console.warn('[Chatbot Embed] Missing data-chatbot-id or data-public-token attributes.');
    }

    // Create chat elements
    function createChatBubble() {
        // Prevent duplicate initializations
        if (document.getElementById('chatbot-bubble-container')) return;

        // Container
        const container = document.createElement('div');
        container.id = 'chatbot-bubble-container';
        container.className = `cb-pos-${CONFIG.position}`;
        
        // Always use avatar URL (default or custom) with cache-busting
        const avatarWithCacheBusting = addCacheBusting(CONFIG.avatarUrl);
        const avatarHtml = `<img src="${avatarWithCacheBusting}" class="cb-header-avatar" alt="Avatar" onerror="this.style.display='none'; this.parentElement.querySelector('.cb-header-avatar-fallback').style.display='flex';">
                            <div class="cb-header-avatar-fallback" style="display:none; width: 42px; height: 42px; border-radius: 50%; background: rgba(255, 255, 255, 0.2); align-items: center; justify-content: center; font-size: 22px; border: 2px solid rgba(255, 255, 255, 0.4);">🤖</div>`;

        container.innerHTML = `
            <!-- Chat Trigger Bubble -->
            <button id="chatbot-trigger-bubble" aria-label="Open Chat">
                💬
            </button>
            
            <!-- Chat Window -->
            <div id="chatbot-window" style="display: none;">
                <!-- Header -->
                <div class="cb-header">
                    <div class="cb-header-info">
                        ${avatarHtml}
                        <div class="cb-header-text">
                            <div class="cb-header-title">${CONFIG.botName}</div>
                            <div class="cb-header-status">
                                <span class="cb-status-dot"></span>
                                Online
                            </div>
                        </div>
                    </div>
                    <button id="chatbot-close-btn" aria-label="Close Chat">×</button>
                </div>
                
                <!-- Messages -->
                <div id="chatbot-messages">
                    <div class="cb-message-wrapper bot">
                        <div class="cb-message">Xin chào! Tôi có thể giúp gì cho bạn hôm nay?</div>
                        <div class="cb-message-time">${formatTime(new Date())}</div>
                    </div>
                </div>
                
                <!-- Input Area -->
                <div id="chatbot-input-area">
                    <textarea id="chatbot-input" placeholder="Nhập tin nhắn..." autocomplete="off" rows="1"></textarea>
                    <button id="chatbot-send-btn" aria-label="Send Message">
                        <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                            <line x1="22" y1="2" x2="11" y2="13"></line>
                            <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
                        </svg>
                    </button>
                </div>
                
                <!-- Powered By -->
                <div class="cb-powered-by">
                    Powered by <a href="https://docx.bittechx.vn/" target="_blank" rel="noopener noreferrer">Bittech RAG</a>
                </div>
            </div>
        `;
        
        document.body.appendChild(container);
        
        // Initialize variables
        input = document.getElementById('chatbot-input');
        sendBtn = document.getElementById('chatbot-send-btn');
        messagesDiv = document.getElementById('chatbot-messages');
        
        // Auto-resize textarea
        function autoResizeTextarea() {
            input.style.height = 'auto';
            input.style.height = Math.min(input.scrollHeight, 120) + 'px';
        }
        input.addEventListener('input', autoResizeTextarea);
        
        // Fetch Chatbot customization from DB to override values
        fetchChatbotDetails();
        
        addStyles();
        addEventListeners();
    }

    // Map color enum to hex colors
    function getColorFromEnum(colorEnum) {
        const colorMap = {
            0: '#4f46e5', // Default Indigo
            1: '#3b82f6', // Blue
            2: '#10b981', // Green
            3: '#8b5cf6', // Purple
            4: '#ec4899'  // Pink
        };
        return colorMap[colorEnum] || colorMap[0];
    }

    async function fetchChatbotDetails() {
        if (!CONFIG.chatbotId || !CONFIG.publicToken) return;
        try {
            const response = await fetch(`${CONFIG.apiBaseUrl}/api/public/chatbot/${CONFIG.chatbotId}`, {
                method: 'GET',
                headers: {
                    'x-public-token': CONFIG.publicToken
                }
            });
            
            if (response.ok) {
                const resData = await response.json();
                if (resData.statusCode === 200 && resData.data) {
                    const botData = resData.data;
                    
                    // Update CONFIG with bot data
                    if (botData.name) CONFIG.botName = botData.name;
                    // Use default avatar if botData.avatar_url is empty, null, or undefined
                    // Ensure the avatar URL is absolute (using API base URL)
                    CONFIG.avatarUrl = botData.avatar_url ? ensureAbsoluteUrl(botData.avatar_url, CONFIG.apiBaseUrl) : defaultAvatarUrl;
                    if (botData.color !== undefined) {
                        CONFIG.themeColor = getColorFromEnum(botData.color);
                    }
                    if (botData.workspace_id) {
                        CONFIG.workspaceId = botData.workspace_id;
                    }
                    if (botData.workflow_webhook_url) {
                        CONFIG.workflowWebhookUrl = botData.workflow_webhook_url;
                    }
                    
                    // Update the greeting message
                    const messagesDiv = document.getElementById('chatbot-messages');
                    const greetingMessage = botData.greeting || 'Xin chào! Tôi có thể giúp gì cho bạn hôm nay?';
                    
                    // Replace the default greeting if it exists
                    const botMessages = messagesDiv.querySelectorAll('.cb-message-wrapper.bot');
                    if (botMessages.length > 0) {
                        const firstBotMessage = botMessages[0].querySelector('.cb-message');
                        if (firstBotMessage) {
                            firstBotMessage.textContent = greetingMessage;
                        }
                    }
                    
                    // Update header title
                    const headerTitle = document.querySelector('.cb-header-title');
                    if (headerTitle) {
                        headerTitle.textContent = CONFIG.botName;
                    }
                    
                    // Update avatar (use default if needed) with cache-busting
                    const headerAvatar = document.querySelector('.cb-header-avatar');
                    if (headerAvatar) {
                        headerAvatar.src = addCacheBusting(CONFIG.avatarUrl);
                        // Show fallback if image fails to load
                        headerAvatar.onerror = function() {
                            this.style.display = 'none';
                            const fallback = this.parentElement.querySelector('.cb-header-avatar-fallback');
                            if (fallback) {
                                fallback.style.display = 'flex';
                            }
                        };
                    }
                    
                    // Re-apply styles with new theme color
                    reapplyStyles();
                    
                    // Fetch suggestions
                    fetchSuggestions();
                }
            }
        } catch (e) {
            console.error('[Chatbot Embed] Init error:', e);
        }
    }

    async function fetchSuggestions() {
        if (!CONFIG.chatbotId || !CONFIG.publicToken) return;
        try {
            const response = await fetch(`${CONFIG.apiBaseUrl}/api/public/chatbot/${CONFIG.chatbotId}/suggest`, {
                method: 'GET',
                headers: {
                    'x-public-token': CONFIG.publicToken
                }
            });
            
            if (response.ok) {
                const resData = await response.json();
                if (resData.statusCode === 200 && resData.data && resData.data.suggestions) {
                    CONFIG.suggestions = resData.data.suggestions;
                    // Render suggestions
                    renderSuggestions();
                }
            }
        } catch (e) {
            console.error('[Chatbot Embed] Fetch suggestions error:', e);
        }
    }

    function escapeHTML(str) {
        return str
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }
    
    function renderSuggestions() {
        if (!messagesDiv || CONFIG.suggestions.length === 0) return;
        
        // Check if suggestions already rendered
        if (document.querySelector('.cb-suggestions-container')) return;
        
        const suggestionsContainer = document.createElement('div');
        suggestionsContainer.className = 'cb-suggestions-container';
        
        const suggestionsTitle = document.createElement('div');
        suggestionsTitle.className = 'cb-suggestions-title';
        suggestionsTitle.textContent = 'Câu hỏi gợi ý:';
        suggestionsContainer.appendChild(suggestionsTitle);
        
        const suggestionsList = document.createElement('div');
        suggestionsList.className = 'cb-suggestions-list';
        
        CONFIG.suggestions.forEach(suggestion => {
            const suggestionBtn = document.createElement('button');
            suggestionBtn.className = 'cb-suggestion-btn';
            suggestionBtn.textContent = suggestion;
            suggestionBtn.addEventListener('click', () => {
                // Fill input and send (only if not already sending)
                if (input && !isSending) {
                    input.value = suggestion;
                    sendMessage();
                }
            });
            suggestionBtn.addEventListener('mouseenter', () => {
                if (!isSending) {
                    suggestionBtn.style.background = CONFIG.themeColor;
                    suggestionBtn.style.color = 'white';
                    suggestionBtn.style.borderColor = CONFIG.themeColor;
                }
            });
            suggestionBtn.addEventListener('mouseleave', () => {
                suggestionBtn.style.background = '#f8fafc';
                suggestionBtn.style.color = '#475569';
                suggestionBtn.style.borderColor = '#e2e8f0';
            });
            suggestionsList.appendChild(suggestionBtn);
        });
        
        suggestionsContainer.appendChild(suggestionsList);
        messagesDiv.appendChild(suggestionsContainer);
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
    }
    
    async function sendMessage() {
        const message = input.value.trim();
        if (!message || isSending) return; // Prevent sending empty or duplicate

        isSending = true; // Lock sending

        // Disable UI while sending
        input.disabled = true;
        sendBtn.disabled = true;
        sendBtn.style.opacity = 0.6;
        sendBtn.style.cursor = 'not-allowed';

        // Clear input
        input.value = '';
        input.style.height = 'auto';

        // Add user message to chat UI
        appendMessage('user', message);

        // Add typing indicator
        const typingIndicator = appendTypingIndicator();

        try {
            const endpoint = CONFIG.workflowWebhookUrl || `${CONFIG.apiBaseUrl}/api/public/chatbot/${CONFIG.chatbotId}/chat`;
            const requestBody = CONFIG.workflowWebhookUrl
                ? {
                    chatbot_id: CONFIG.chatbotId,
                    public_token: CONFIG.publicToken,
                    message: message,
                    sessionId: CONFIG.sessionId
                  }
                : {
                    message: message,
                    sessionId: CONFIG.sessionId
                  };
            const response = await fetch(endpoint, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'x-public-token': CONFIG.publicToken
                },
                body: JSON.stringify(requestBody)
            });
            
            // Remove typing indicator
            typingIndicator.remove();

            const resData = await response.json();
            
            if (response.ok && resData.statusCode === 200) {
                // Store the session ID for subsequent messages and save to localStorage
                if (resData.data.sessionId) {
                    CONFIG.sessionId = resData.data.sessionId;
                    localStorage.setItem(STORAGE_KEY, resData.data.sessionId);
                }
                appendMessage('bot', resData.data.answer);
            } else {
                // Handle specific errors
                let errorMsg = resData.message || 'Xin lỗi, tôi đã gặp sự cố khi xử lý tin nhắn của bạn. Vui lòng thử lại sau.';
                
                if (response.status === 429) { // Too Many Requests (rate limit)
                    errorMsg = 'Bạn đã gửi quá nhiều tin nhắn! Vui lòng chờ một chút rồi thử lại nhé.';
                } else if (response.status === 403 && 'quota' in resData.message?.toLowerCase()) {
                    errorMsg = 'Tài khoản chủ shop đã hết lượt sử dụng! Vui lòng liên hệ chủ shop để biết thêm chi tiết.';
                }
                
                appendMessage('bot', errorMsg);
            }
        } catch (error) {
            console.error('Chat error:', error);
            typingIndicator.remove();
            appendMessage('bot', 'Xin lỗi, không thể kết nối đến máy chủ. Vui lòng kiểm tra kết nối mạng của bạn.');
        } finally {
            // Re-enable UI
            isSending = false;
            input.disabled = false;
            sendBtn.disabled = false;
            sendBtn.style.opacity = 1;
            sendBtn.style.cursor = 'pointer';
            input.focus(); // Focus back on input
        }
    }

    function appendMessage(sender, text) {
        const wrapper = document.createElement('div');
        wrapper.className = `cb-message-wrapper ${sender}`;
        
        // Format markdown-like elements (simple bold and line breaks)
        let formattedText = escapeHTML(text)
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/\n/g, '<br>');

        const messageDiv = document.createElement('div');
        messageDiv.className = 'cb-message';
        messageDiv.innerHTML = formattedText;
        
        if (sender === 'user') {
            messageDiv.style.background = CONFIG.themeColor;
        }

        const timeDiv = document.createElement('div');
        timeDiv.className = 'cb-message-time';
        timeDiv.textContent = formatTime(new Date());

        wrapper.appendChild(messageDiv);
        wrapper.appendChild(timeDiv);
        messagesDiv.appendChild(wrapper);
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
    }

    function appendTypingIndicator() {
        const wrapper = document.createElement('div');
        wrapper.className = 'cb-message-wrapper bot cb-typing-wrapper';
        wrapper.innerHTML = `
            <div class="cb-typing-indicator">
                <span class="cb-typing-dot"></span>
                <span class="cb-typing-dot"></span>
                <span class="cb-typing-dot"></span>
            </div>
        `;
        messagesDiv.appendChild(wrapper);
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
        return wrapper;
    }
    
    function reapplyStyles() {
        // Update all dynamic style elements that use CONFIG.themeColor
        const trigger = document.getElementById('chatbot-trigger-bubble');
        const header = document.querySelector('.cb-header');
        const userMessages = document.querySelectorAll('.user .cb-message');
        const sendBtn = document.getElementById('chatbot-send-btn');
        const poweredByLink = document.querySelector('.cb-powered-by a');
        const input = document.getElementById('chatbot-input');
        const suggestionBtns = document.querySelectorAll('.cb-suggestion-btn');
        
        if (trigger) {
            trigger.style.setProperty('background', `linear-gradient(135deg, ${CONFIG.themeColor}, ${darkenColor(CONFIG.themeColor, 15)})`, 'important');
        }
        if (header) {
            header.style.background = `linear-gradient(135deg, ${CONFIG.themeColor}, ${darkenColor(CONFIG.themeColor, 15)})`;
        }
        userMessages.forEach(msg => {
            msg.style.background = CONFIG.themeColor;
        });
        if (sendBtn) {
            sendBtn.style.background = CONFIG.themeColor;
        }
        if (poweredByLink) {
            poweredByLink.style.color = CONFIG.themeColor;
        }
        suggestionBtns.forEach(btn => {
            btn.addEventListener('mouseenter', () => {
                btn.style.background = CONFIG.themeColor;
                btn.style.color = 'white';
                btn.style.borderColor = CONFIG.themeColor;
            });
            btn.addEventListener('mouseleave', () => {
                btn.style.background = '#f8fafc';
                btn.style.color = '#475569';
                btn.style.borderColor = '#e2e8f0';
            });
        });
        
        // Update input focus styles by updating the style element
        const existingStyles = document.querySelector('#chatbot-dynamic-styles');
        if (existingStyles) {
            existingStyles.textContent = `
                #chatbot-trigger-bubble {
                    background: linear-gradient(135deg, ${CONFIG.themeColor}, ${darkenColor(CONFIG.themeColor, 15)}) !important;
                }
                #chatbot-trigger-bubble:hover {
                    background: linear-gradient(135deg, ${darkenColor(CONFIG.themeColor, 5)}, ${darkenColor(CONFIG.themeColor, 20)}) !important;
                }
                #chatbot-input:focus {
                    border-color: ${CONFIG.themeColor};
                    box-shadow: 0 0 0 3px ${rgbaColor(CONFIG.themeColor, 0.15)};
                }
                #chatbot-send-btn:hover {
                    background: ${darkenColor(CONFIG.themeColor, 10)};
                }
                .cb-suggestion-btn:hover {
                    background: ${CONFIG.themeColor};
                    color: white;
                    border-color: ${CONFIG.themeColor};
                }
            `;
        } else {
            const dynamicStyles = document.createElement('style');
            dynamicStyles.id = 'chatbot-dynamic-styles';
            dynamicStyles.textContent = `
                #chatbot-trigger-bubble {
                    background: linear-gradient(135deg, ${CONFIG.themeColor}, ${darkenColor(CONFIG.themeColor, 15)}) !important;
                }
                #chatbot-trigger-bubble:hover {
                    background: linear-gradient(135deg, ${darkenColor(CONFIG.themeColor, 5)}, ${darkenColor(CONFIG.themeColor, 20)}) !important;
                }
                #chatbot-input:focus {
                    border-color: ${CONFIG.themeColor};
                    box-shadow: 0 0 0 3px ${rgbaColor(CONFIG.themeColor, 0.15)};
                }
                #chatbot-send-btn:hover {
                    background: ${darkenColor(CONFIG.themeColor, 10)};
                }
                .cb-suggestion-btn:hover {
                    background: ${CONFIG.themeColor};
                    color: white;
                    border-color: ${CONFIG.themeColor};
                }
            `;
            document.head.appendChild(dynamicStyles);
        }
    }

    function formatTime(date) {
        return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }

    // Add styles with premium CSS
    function addStyles() {
        const styles = document.createElement('style');
        styles.textContent = `
            #chatbot-bubble-container {
                position: fixed;
                bottom: 24px;
                z-index: 999999;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
                display: flex;
                flex-direction: column;
                align-items: flex-end;
            }
            .cb-pos-bottom-right {
                right: 24px;
            }
            .cb-pos-bottom-left {
                left: 24px;
                align-items: flex-start !important;
            }
            
            /* Premium Trigger Bubble */
            #chatbot-trigger-bubble {
                width: 60px;
                height: 60px;
                border-radius: 50%;
                background: linear-gradient(135deg, ${CONFIG.themeColor}, ${darkenColor(CONFIG.themeColor, 15)});
                color: white;
                border: none;
                cursor: pointer;
                box-shadow: 0 8px 24px rgba(0, 0, 0, 0.15);
                display: flex;
                align-items: center;
                justify-content: center;
                transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
                outline: none;
                position: relative;
                font-size: 28px;
            }
            #chatbot-trigger-bubble:hover {
                transform: scale(1.05) translateY(-2px);
                box-shadow: 0 12px 30px rgba(0, 0, 0, 0.2);
            }
            #chatbot-trigger-bubble:active {
                transform: scale(0.95);
            }

            
            /* Chat Window Container */
            #chatbot-window {
                width: 380px;
                height: 600px;
                max-height: calc(100vh - 120px);
                background: rgba(255, 255, 255, 0.95);
                backdrop-filter: blur(10px);
                -webkit-backdrop-filter: blur(10px);
                border-radius: 20px;
                box-shadow: 0 12px 40px rgba(0, 0, 0, 0.15);
                display: flex;
                flex-direction: column;
                overflow: hidden;
                margin-bottom: 16px;
                animation: cb-slide-in 0.4s cubic-bezier(0.16, 1, 0.3, 1);
                border: 1px solid rgba(0, 0, 0, 0.08);
            }
            
            @keyframes cb-slide-in {
                from {
                    opacity: 0;
                    transform: translateY(30px) scale(0.95);
                }
                to {
                    opacity: 1;
                    transform: translateY(0) scale(1);
                }
            }
            
            /* Header */
            .cb-header {
                background: linear-gradient(135deg, ${CONFIG.themeColor}, ${darkenColor(CONFIG.themeColor, 15)});
                color: white;
                padding: 16px 20px;
                display: flex;
                align-items: center;
                justify-content: space-between;
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
            }
            .cb-header-info {
                display: flex;
                align-items: center;
                gap: 12px;
            }
            .cb-header-avatar {
                width: 42px;
                height: 42px;
                border-radius: 50%;
                object-fit: cover;
                border: 2px solid rgba(255, 255, 255, 0.8);
                box-shadow: 0 2px 6px rgba(0, 0, 0, 0.1);
            }
            .cb-header-avatar-default {
                width: 42px;
                height: 42px;
                border-radius: 50%;
                background: rgba(255, 255, 255, 0.2);
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 22px;
                border: 2px solid rgba(255, 255, 255, 0.4);
            }
            .cb-header-text {
                display: flex;
                flex-direction: column;
            }
            .cb-header-title {
                font-weight: 600;
                font-size: 16px;
                letter-spacing: 0.3px;
            }
            .cb-header-status {
                font-size: 12px;
                opacity: 0.9;
                display: flex;
                align-items: center;
                gap: 5px;
                margin-top: 2px;
            }
            .cb-status-dot {
                width: 8px;
                height: 8px;
                background-color: #10b981; /* Green */
                border-radius: 50%;
                display: inline-block;
                animation: cb-pulse 2s infinite;
            }
            
            @keyframes cb-pulse {
                0% {
                    box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7);
                }
                70% {
                    box-shadow: 0 0 0 6px rgba(16, 185, 129, 0);
                }
                100% {
                    box-shadow: 0 0 0 0 rgba(16, 185, 129, 0);
                }
            }
            
            #chatbot-close-btn {
                background: transparent;
                border: none;
                color: rgba(255, 255, 255, 0.8);
                font-size: 28px;
                cursor: pointer;
                line-height: 1;
                padding: 4px;
                transition: color 0.2s;
            }
            #chatbot-close-btn:hover {
                color: white;
            }
            
            /* Messages Area */
            #chatbot-messages {
                flex: 1;
                overflow-y: auto;
                padding: 20px;
                display: flex;
                flex-direction: column;
                gap: 16px;
                background: #f8fafc;
                scroll-behavior: smooth;
            }
            
            /* Scrollbar */
            #chatbot-messages::-webkit-scrollbar {
                width: 6px;
            }
            #chatbot-messages::-webkit-scrollbar-track {
                background: transparent;
            }
            #chatbot-messages::-webkit-scrollbar-thumb {
                background: #cbd5e1;
                border-radius: 10px;
            }
            #chatbot-messages::-webkit-scrollbar-thumb:hover {
                background: #94a3b8;
            }
            
            /* Chat Bubbles */
            .cb-message-wrapper {
                display: flex;
                flex-direction: column;
                max-width: 82%;
                animation: cb-bubble-pop 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
            }
            
            @keyframes cb-bubble-pop {
                from {
                    transform: scale(0.85);
                    opacity: 0;
                }
                to {
                    transform: scale(1);
                    opacity: 1;
                }
            }
            
            .cb-message-wrapper.bot {
                align-self: flex-start;
            }
            .cb-message-wrapper.user {
                align-self: flex-end;
            }
            
            .cb-message {
                padding: 12px 16px;
                font-size: 14px;
                line-height: 1.5;
                box-shadow: 0 2px 4px rgba(0,0,0,0.02);
            }
            
            .bot .cb-message {
                background: white;
                color: #1e293b;
                border-radius: 4px 16px 16px 16px;
                border: 1px solid #f1f5f9;
                text-align: left;
            }
            .user .cb-message {
                background: ${CONFIG.themeColor};
                color: white;
                border-radius: 16px 16px 4px 16px;
                text-align: right;
            }
            
            .cb-message-time {
                font-size: 10px;
                color: #94a3b8;
                margin-top: 4px;
                padding: 0 4px;
            }
            .bot .cb-message-time {
                align-self: flex-start;
            }
            .user .cb-message-time {
                align-self: flex-end;
            }
            
            /* Sources list styling */
            .cb-sources-container {
                margin-top: 6px;
                padding-top: 6px;
                border-top: 1px dashed rgba(0,0,0,0.06);
                font-size: 11px;
                color: #64748b;
            }
            .cb-source-tag {
                display: inline-block;
                background: #f1f5f9;
                padding: 2px 6px;
                border-radius: 4px;
                margin-right: 4px;
                margin-top: 4px;
                max-width: 150px;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
                vertical-align: middle;
            }
            
            /* Typing indicator */
            .cb-typing-indicator {
                display: flex;
                align-items: center;
                gap: 4px;
                padding: 12px 20px;
                background: white;
                border-radius: 4px 16px 16px 16px;
                width: fit-content;
                box-shadow: 0 2px 4px rgba(0,0,0,0.02);
                border: 1px solid #f1f5f9;
            }
            .cb-typing-dot {
                width: 6px;
                height: 6px;
                background-color: #94a3b8;
                border-radius: 50%;
                animation: cb-typing-bounce 1.4s infinite ease-in-out;
            }
            .cb-typing-dot:nth-child(1) { animation-delay: -0.32s; }
            .cb-typing-dot:nth-child(2) { animation-delay: -0.16s; }
            
            @keyframes cb-typing-bounce {
                0%, 80%, 100% { transform: scale(0); }
                40% { transform: scale(1); }
            }
            
            /* Input Area */
            #chatbot-input-area {
                padding: 14px 20px;
                background: white;
                display: flex;
                align-items: center;
                gap: 12px;
                border-top: 1px solid #f1f5f9;
            }
            #chatbot-input {
                flex: 1;
                border: 1px solid #cbd5e1;
                border-radius: 24px;
                padding: 10px 16px;
                font-size: 14px;
                outline: none;
                transition: all 0.2s;
                color: #1e293b;
                resize: none;
                max-height: 120px;
                overflow-y: auto;
                line-height: 1.5;
                font-family: inherit;
            }
            #chatbot-input:focus {
                border-color: ${CONFIG.themeColor};
                box-shadow: 0 0 0 3px ${rgbaColor(CONFIG.themeColor, 0.15)};
            }
            #chatbot-send-btn {
                background: ${CONFIG.themeColor};
                color: white;
                border: none;
                width: 40px;
                height: 40px;
                border-radius: 50%;
                cursor: pointer;
                display: flex;
                align-items: center;
                justify-content: center;
                transition: all 0.2s;
                flex-shrink: 0;
            }
            #chatbot-send-btn:hover {
                transform: scale(1.05);
                background: ${darkenColor(CONFIG.themeColor, 10)};
            }
            #chatbot-send-btn:active {
                transform: scale(0.95);
            }
            
            /* Powered By */
            .cb-powered-by {
                text-align: center;
                padding: 6px;
                font-size: 10px;
                color: #94a3b8;
                background: #f8fafc;
                border-top: 1px solid #f1f5f9;
            }
            .cb-powered-by a {
                color: ${CONFIG.themeColor};
                text-decoration: none;
                font-weight: 500;
            }
            
            /* Suggestions styles */
            .cb-suggestions-container {
                padding: 12px 20px;
                background: white;
                border-top: 1px solid #f1f5f9;
            }
            .cb-suggestions-title {
                font-size: 12px;
                color: #64748b;
                margin-bottom: 8px;
                font-weight: 500;
            }
            .cb-suggestions-list {
                display: flex;
                flex-direction: column;
                gap: 8px;
            }
            .cb-suggestion-btn {
                background: #f8fafc;
                border: 1px solid #e2e8f0;
                border-radius: 8px;
                padding: 8px 12px;
                font-size: 13px;
                color: #475569;
                text-align: left;
                cursor: pointer;
                transition: all 0.2s;
                width: 100%;
            }
            .cb-suggestion-btn:hover {
                background: ${CONFIG.themeColor};
                color: white;
                border-color: ${CONFIG.themeColor};
            }

            /* Responsive adjustments */
            @media (max-width: 480px) {
                #chatbot-window {
                    width: calc(100vw - 32px);
                    height: calc(100vh - 100px);
                    right: -8px;
                }
                .cb-pos-bottom-left #chatbot-window {
                    left: -8px;
                }
            }
        `;
        document.head.appendChild(styles);
    }

    // Add event listeners
    function addEventListeners() {
        const trigger = document.getElementById('chatbot-trigger-bubble');
        const windowDiv = document.getElementById('chatbot-window');
        const closeBtn = document.getElementById('chatbot-close-btn');

        let isChatOpen = false;

        function toggleChat() {
            isChatOpen = !isChatOpen;
            if (isChatOpen) {
                windowDiv.style.display = 'flex';
                trigger.style.display = 'none';
                input.focus();
            } else {
                windowDiv.style.display = 'none';
                trigger.style.display = 'flex';
            }
        }

        trigger.addEventListener('click', toggleChat);
        closeBtn.addEventListener('click', toggleChat);
        
        sendBtn.addEventListener('click', sendMessage);
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });
    }

    // Helper functions for dynamic theme colors
    function darkenColor(hex, percent) {
        hex = hex.replace(/^\s*#|\s*$/g, '');
        if(hex.length == 3) hex = hex.replace(/(.)/g, '$1$1');
        let r = parseInt(hex.substr(0, 2), 16),
            g = parseInt(hex.substr(2, 2), 16),
            b = parseInt(hex.substr(4, 2), 16);

        r = Math.max(0, Math.min(255, r - (255 * (percent / 100))));
        g = Math.max(0, Math.min(255, g - (255 * (percent / 100))));
        b = Math.max(0, Math.min(255, b - (255 * (percent / 100))));

        return `#${Math.round(r).toString(16).padStart(2, '0')}${Math.round(g).toString(16).padStart(2, '0')}${Math.round(b).toString(16).padStart(2, '0')}`;
    }

    function rgbaColor(hex, alpha) {
        hex = hex.replace(/^\s*#|\s*$/g, '');
        if(hex.length == 3) hex = hex.replace(/(.)/g, '$1$1');
        let r = parseInt(hex.substr(0, 2), 16),
            g = parseInt(hex.substr(2, 2), 16),
            b = parseInt(hex.substr(4, 2), 16);

        return `rgba(${r}, ${g}, ${b}, ${alpha})`;
    }

    // Initialize
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', createChatBubble);
    } else {
        createChatBubble();
    }
})();
