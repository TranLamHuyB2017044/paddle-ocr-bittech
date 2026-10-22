/**
 * Chatbot Embed Script - Premium Responsive Version
 * Usage: <script src="http://your-domain/chatbot-embed.js" data-chatbot-id="YOUR_ID" data-public-token="YOUR_TOKEN"></script>
 */
(function () {
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
    const CATEGORY_STORAGE_KEY = `chatbot_category_${scriptTag?.getAttribute('data-chatbot-id') || ''}`;

    const CONFIG = {
        chatbotId: scriptTag?.getAttribute('data-chatbot-id') || '',
        publicToken: scriptTag?.getAttribute('data-public-token') || '',
        apiBaseUrl: scriptTag?.getAttribute('data-api-url') || autoApiUrl,
        position: scriptTag?.getAttribute('data-position') || 'bottom-right',
        themeColor: scriptTag?.getAttribute('data-theme-color') || '#4f46e5', // Sleek Indigo
        botName: scriptTag?.getAttribute('data-bot-name') || 'AI Assistant',
        avatarUrl: scriptTag?.getAttribute('data-avatar-url') || '',
        workspaceId: null,
        workflowWebhookUrl: scriptTag?.getAttribute('data-webhook-url') || null,
        suggestions: [],
        sessionId: localStorage.getItem(STORAGE_KEY) || null,
        showSources: false,
        categories: [],
        activeCategory: localStorage.getItem(CATEGORY_STORAGE_KEY) || null
    };

    let input, sendBtn, messagesDiv, mentionPopup, categoryChipContainer;
    let isSending = false; // Prevent duplicate requests
    let mentionSelectedIndex = -1;
    let filteredCategories = [];

    // Cache gợi ý theo chuyên mục: { '__all__': [...], 'nha-dat': [...], ... }
    const suggestionsCache = new Map();
    const SUGGESTIONS_CACHE_PREFIX = `cb_sug_${CONFIG.chatbotId || 'bot'}_`;

    function getCachedSuggestions(category) {
        const key = category || '__all__';
        if (suggestionsCache.has(key)) {
            return suggestionsCache.get(key);
        }
        try {
            const raw = sessionStorage.getItem(SUGGESTIONS_CACHE_PREFIX + key);
            if (raw) {
                const parsed = JSON.parse(raw);
                if (Array.isArray(parsed)) {
                    suggestionsCache.set(key, parsed);
                    return parsed;
                }
            }
        } catch (e) {}
        return null;
    }

    function setCachedSuggestions(category, list) {
        const key = category || '__all__';
        suggestionsCache.set(key, list);
        try {
            sessionStorage.setItem(SUGGESTIONS_CACHE_PREFIX + key, JSON.stringify(list));
        } catch (e) {}
    }

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
                    <div class="cb-header-actions">
                        <button id="chatbot-close-btn" aria-label="Close Chat">×</button>
                    </div>
                </div>

                <!-- Active Category Bar -->
                <div id="cb-category-chip-container" class="cb-category-bar" style="display: none;"></div>
                
                <!-- Messages -->
                <div id="chatbot-messages">
                    <div class="cb-message-wrapper bot">
                        <div class="cb-message">Xin chào! Tôi có thể giúp gì cho bạn hôm nay?</div>
                        <div class="cb-message-time">${formatTime(new Date())}</div>
                    </div>
                </div>

                <!-- Mention Autocomplete Popup -->
                <div id="cb-mention-popup" class="cb-mention-popup" style="display: none;"></div>
                
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
                    Powered by <a href="https://docx.bittechx.vn/" target="_blank" rel="noopener noreferrer">Bittech</a>
                </div>
            </div>
        `;

        document.body.appendChild(container);

        // Initialize variables
        input = document.getElementById('chatbot-input');
        sendBtn = document.getElementById('chatbot-send-btn');
        messagesDiv = document.getElementById('chatbot-messages');
        mentionPopup = document.getElementById('cb-mention-popup');
        categoryChipContainer = document.getElementById('cb-category-chip-container');

        // Auto-resize textarea
        function autoResizeTextarea() {
            input.style.height = 'auto';
            input.style.height = Math.max(46, Math.min(input.scrollHeight, 140)) + 'px';
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
                    if (botData.show_sources !== undefined) {
                        CONFIG.showSources = Boolean(botData.show_sources);
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
                        headerAvatar.onerror = function () {
                            this.style.display = 'none';
                            const fallback = this.parentElement.querySelector('.cb-header-avatar-fallback');
                            if (fallback) {
                                fallback.style.display = 'flex';
                            }
                        };
                    }

                    // Re-apply styles with new theme color
                    reapplyStyles();

                    // Fetch suggestions & categories
                    fetchSuggestions();
                    fetchCategories();
                }
            }
        } catch (e) {
            console.error('[Chatbot Embed] Init error:', e);
        }
    }

    async function fetchCategories() {
        if (!CONFIG.chatbotId || !CONFIG.publicToken) return;
        try {
            const response = await fetch(`${CONFIG.apiBaseUrl}/api/public/chatbot/${CONFIG.chatbotId}/categories`, {
                method: 'GET',
                headers: {
                    'x-public-token': CONFIG.publicToken
                }
            });
            if (response.ok) {
                const resData = await response.json();
                if (resData.statusCode === 200 && Array.isArray(resData.data)) {
                    CONFIG.categories = resData.data;
                    // Validate currently stored activeCategory
                    if (CONFIG.activeCategory) {
                        const exists = CONFIG.categories.some(c => c.slug === CONFIG.activeCategory);
                        if (!exists) {
                            CONFIG.activeCategory = null;
                            localStorage.removeItem(CATEGORY_STORAGE_KEY);
                        }
                    }
                    renderCategoriesBar();
                    if (CONFIG.activeCategory) {
                        setTimeout(() => {
                            const activePill = categoryChipContainer.querySelector('.cb-category-pill.active');
                            if (activePill) {
                                activePill.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
                            }
                        }, 100);
                        fetchSuggestions(CONFIG.activeCategory);
                    }
                }
            }
        } catch (e) {
            console.error('[Chatbot Embed] Fetch categories error:', e);
        }
    }

    function setActiveCategory(categorySlug) {
        CONFIG.activeCategory = categorySlug || null;
        if (CONFIG.activeCategory) {
            localStorage.setItem(CATEGORY_STORAGE_KEY, CONFIG.activeCategory);
        } else {
            localStorage.removeItem(CATEGORY_STORAGE_KEY);
        }
        renderCategoriesBar();

        // Tự động cuộn pill được chọn vào giữa tầm nhìn
        if (categoryChipContainer) {
            setTimeout(() => {
                const activePill = categoryChipContainer.querySelector('.cb-category-pill.active');
                if (activePill) {
                    activePill.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
                }
            }, 50);
        }

        // Tự động tải lại câu hỏi gợi ý theo chuyên mục được chọn (nếu chưa chat)
        if (messagesDiv && messagesDiv.querySelectorAll('.cb-message-wrapper').length <= 1) {
            fetchSuggestions(CONFIG.activeCategory);
        }
    }

    function renderCategoriesBar() {
        if (!categoryChipContainer) return;
        if (!CONFIG.categories || CONFIG.categories.length === 0) {
            categoryChipContainer.innerHTML = '';
            categoryChipContainer.style.display = 'none';
            return;
        }

        categoryChipContainer.style.display = 'flex';
        categoryChipContainer.innerHTML = '';

        // Nút 'Tất cả'
        const allBtn = document.createElement('button');
        allBtn.type = 'button';
        allBtn.className = `cb-category-pill ${!CONFIG.activeCategory ? 'active' : ''}`;
        allBtn.innerHTML = `<span class="cb-category-pill-name">Tất cả</span>`;
        allBtn.title = 'Tìm kiếm trong toàn bộ kho tài liệu';
        allBtn.addEventListener('click', () => {
            setActiveCategory(null);
        });
        categoryChipContainer.appendChild(allBtn);

        // Các nút category
        CONFIG.categories.forEach(cat => {
            const isSelected = CONFIG.activeCategory === cat.slug;
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = `cb-category-pill ${isSelected ? 'active' : ''}`;
            const icon = cat.icon || '🏷️';
            btn.innerHTML = `
                <span class="cb-category-pill-icon">${escapeHTML(icon)}</span>
                <span class="cb-category-pill-name">${escapeHTML(cat.name)}</span>
                ${isSelected ? '<span class="cb-category-pill-clear" title="Bỏ chọn">✕</span>' : ''}
            `;
            btn.title = `Chuyên mục: ${cat.name}`;
            btn.addEventListener('click', (e) => {
                // Nếu bấm vào icon clear hoặc bấm lại category đang chọn -> bỏ chọn
                if (isSelected) {
                    setActiveCategory(null);
                } else {
                    setActiveCategory(cat.slug);
                }
            });
            categoryChipContainer.appendChild(btn);
        });
    }

    // Mention Autocomplete Handlers
    function showMentionPopup(query) {
        if (!mentionPopup || !CONFIG.categories || CONFIG.categories.length === 0) {
            hideMentionPopup();
            return;
        }

        const q = (query || '').toLowerCase().trim();
        filteredCategories = CONFIG.categories.filter(c =>
            !q || (c.name && c.name.toLowerCase().includes(q)) || (c.slug && c.slug.toLowerCase().includes(q))
        );

        if (filteredCategories.length === 0) {
            hideMentionPopup();
            return;
        }

        mentionSelectedIndex = 0;
        renderMentionPopup();
        mentionPopup.style.display = 'block';
    }

    function hideMentionPopup() {
        if (mentionPopup) {
            mentionPopup.style.display = 'none';
            mentionPopup.innerHTML = '';
        }
        mentionSelectedIndex = -1;
        filteredCategories = [];
    }

    function renderMentionPopup() {
        if (!mentionPopup) return;
        mentionPopup.innerHTML = '';

        const header = document.createElement('div');
        header.className = 'cb-mention-header';
        header.textContent = 'Chọn chuyên mục';
        mentionPopup.appendChild(header);

        filteredCategories.forEach((cat, index) => {
            const item = document.createElement('div');
            item.className = `cb-mention-item ${index === mentionSelectedIndex ? 'active' : ''}`;
            const icon = cat.icon || '🏷️';
            item.innerHTML = `
                <span class="cb-mention-icon">${escapeHTML(icon)}</span>
                <div class="cb-mention-info">
                    <span class="cb-mention-name">${escapeHTML(cat.name)}</span>
                    <span class="cb-mention-slug">${escapeHTML(cat.slug)}</span>
                </div>
            `;
            item.addEventListener('mouseenter', () => {
                mentionSelectedIndex = index;
                updateMentionSelectedClass();
            });
            item.addEventListener('mousedown', (e) => {
                e.preventDefault(); // Prevent blur
                selectCategory(cat);
            });
            mentionPopup.appendChild(item);
        });
    }

    function updateMentionSelectedClass() {
        if (!mentionPopup) return;
        const items = mentionPopup.querySelectorAll('.cb-mention-item');
        items.forEach((it, idx) => {
            if (idx === mentionSelectedIndex) {
                it.classList.add('active');
                it.scrollIntoView({ block: 'nearest' });
            } else {
                it.classList.remove('active');
            }
        });
    }

    function selectCategory(category) {
        setActiveCategory(category.slug);
        // Remove the @mention token from input
        if (input) {
            const val = input.value;
            const cursorPos = input.selectionStart || val.length;
            const before = val.substring(0, cursorPos);
            const atIndex = before.lastIndexOf('@');
            if (atIndex !== -1) {
                const after = val.substring(cursorPos);
                input.value = (val.substring(0, atIndex) + after).replace(/\s{2,}/g, ' ');
            }
            input.focus();
        }
        hideMentionPopup();
    }

    function checkMentionTrigger() {
        if (!input || !CONFIG.categories || CONFIG.categories.length === 0) return;
        const val = input.value;
        const cursorPos = input.selectionStart || val.length;
        const textBeforeCursor = val.substring(0, cursorPos);
        const atIndex = textBeforeCursor.lastIndexOf('@');

        if (atIndex !== -1) {
            // Check that @ is at start or preceded by space
            const charBeforeAt = atIndex > 0 ? textBeforeCursor[atIndex - 1] : ' ';
            if (charBeforeAt === ' ' || charBeforeAt === '\n') {
                const query = textBeforeCursor.substring(atIndex + 1);
                // Don't trigger if user typed a space after @
                if (!query.includes(' ')) {
                    showMentionPopup(query);
                    return;
                }
            }
        }
        hideMentionPopup();
    }

    function renderSuggestionsSkeleton() {
        if (!messagesDiv) return;
        // Check if suggestions or skeleton already rendered
        if (document.querySelector('.cb-suggestions-container')) return;

        const suggestionsContainer = document.createElement('div');
        suggestionsContainer.className = 'cb-suggestions-container cb-suggestions-skeleton-wrapper';

        const suggestionsTitle = document.createElement('div');
        suggestionsTitle.className = 'cb-suggestions-skeleton-title cb-skeleton-shimmer';
        suggestionsContainer.appendChild(suggestionsTitle);

        const suggestionsList = document.createElement('div');
        suggestionsList.className = 'cb-suggestions-list';

        // Tạo 3 thanh skeleton nút gợi ý với độ dài tự nhiên
        [88, 96, 75].forEach(widthPercent => {
            const skeletonBtn = document.createElement('div');
            skeletonBtn.className = 'cb-suggestion-skeleton-btn cb-skeleton-shimmer';
            skeletonBtn.style.width = widthPercent + '%';
            suggestionsList.appendChild(skeletonBtn);
        });

        suggestionsContainer.appendChild(suggestionsList);
        messagesDiv.appendChild(suggestionsContainer);
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
    }

    function removeSuggestionsSkeleton() {
        const skeletonWrapper = document.querySelector('.cb-suggestions-skeleton-wrapper');
        if (skeletonWrapper) {
            skeletonWrapper.remove();
        }
    }

    async function fetchSuggestions(category = null) {
        if (!CONFIG.chatbotId || !CONFIG.publicToken) return;

        // Xóa gợi ý cũ trước đó nếu có (khi đổi category)
        const oldSuggestions = document.querySelector('.cb-suggestions-container:not(.cb-suggestions-skeleton-wrapper)');
        if (oldSuggestions) {
            oldSuggestions.remove();
        }

        // 1. Kiểm tra cache trước - nếu đã có thì hiển thị ngay lập tức (không gọi lại API)
        const cached = getCachedSuggestions(category);
        if (cached && Array.isArray(cached) && cached.length > 0) {
            CONFIG.suggestions = cached;
            removeSuggestionsSkeleton();
            renderSuggestions();
            return;
        }

        // 2. Nếu chưa có trong cache thì mới hiển thị skeleton và gọi API
        renderSuggestionsSkeleton();

        try {
            const catParam = category ? `?category=${encodeURIComponent(category)}` : '';
            const response = await fetch(`${CONFIG.apiBaseUrl}/api/public/chatbot/${CONFIG.chatbotId}/suggest${catParam}`, {
                method: 'GET',
                headers: {
                    'x-public-token': CONFIG.publicToken
                }
            });

            if (response.ok) {
                const resData = await response.json();
                if (resData.statusCode === 200 && resData.data && Array.isArray(resData.data.suggestions) && resData.data.suggestions.length > 0) {
                    CONFIG.suggestions = resData.data.suggestions;
                    // Lưu vào cache
                    setCachedSuggestions(category, CONFIG.suggestions);
                    removeSuggestionsSkeleton();
                    renderSuggestions();
                    return;
                }
            }
        } catch (e) {
            console.error('[Chatbot Embed] Fetch suggestions error:', e);
        }

        // Xóa skeleton nếu không có suggestion hoặc lỗi
        removeSuggestionsSkeleton();
    }

    function escapeHTML(str) {
        return (str || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function renderSuggestions() {
        if (!messagesDiv || CONFIG.suggestions.length === 0) return;

        // Check if suggestions already rendered
        const existing = document.querySelector('.cb-suggestions-container:not(.cb-suggestions-skeleton-wrapper)');
        if (existing) {
            existing.remove();
        }

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
        hideMentionPopup();

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
                    sessionId: CONFIG.sessionId,
                    category: CONFIG.activeCategory || null,
                    show_sources: CONFIG.showSources
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
                appendMessage('bot', resData.data.answer, resData.data.sources);
            } else {
                // Handle specific errors
                let errorMsg = resData.message || 'Xin lỗi, tôi đã gặp sự cố khi xử lý tin nhắn của bạn. Vui lòng thử lại sau.';

                if (response.status === 429) { // Too Many Requests (rate limit)
                    errorMsg = 'Bạn đã gửi quá nhiều tin nhắn! Vui lòng chờ một chút rồi thử lại nhé.';
                } else if (response.status === 403 && (resData.message || '').toLowerCase().includes('quota')) {
                    errorMsg = 'Tài khoản chủ chatbot đã hết lượt sử dụng trong tháng! Vui lòng nâng cấp gói hoặc liên hệ quản trị viên.';
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

    function appendMessage(sender, text, sources) {
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

        // Render sources if available and requested
        if (sender === 'bot' && Array.isArray(sources) && sources.length > 0) {
            const sourcesDiv = document.createElement('div');
            sourcesDiv.className = 'cb-sources-container';
            const titleSpan = document.createElement('span');
            titleSpan.className = 'cb-sources-title';
            titleSpan.textContent = 'Nguồn tham khảo: ';
            sourcesDiv.appendChild(titleSpan);

            sources.forEach(src => {
                const tag = document.createElement('span');
                tag.className = 'cb-source-tag';
                const filename = typeof src === 'string' ? src : (src.filename || src.title || JSON.stringify(src));
                tag.textContent = filename;
                tag.title = filename;
                sourcesDiv.appendChild(tag);
            });
            messageDiv.appendChild(sourcesDiv);
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

        // Update input focus & category pill active styles by updating the style element
        const dynamicCss = `
            #chatbot-trigger-bubble {
                background: linear-gradient(135deg, ${CONFIG.themeColor}, ${darkenColor(CONFIG.themeColor, 15)}) !important;
            }
            #chatbot-trigger-bubble:hover {
                background: linear-gradient(135deg, ${darkenColor(CONFIG.themeColor, 5)}, ${darkenColor(CONFIG.themeColor, 20)}) !important;
            }
            #chatbot-input:focus {
                border-color: ${CONFIG.themeColor} !important;
                box-shadow: 0 0 0 3px ${rgbaColor(CONFIG.themeColor, 0.15)} !important;
            }
            #chatbot-send-btn {
                background: ${CONFIG.themeColor} !important;
            }
            #chatbot-send-btn:hover {
                background: ${darkenColor(CONFIG.themeColor, 10)} !important;
            }
            .cb-suggestion-btn:hover {
                background: ${CONFIG.themeColor} !important;
                color: white !important;
                border-color: ${CONFIG.themeColor} !important;
            }
            .cb-category-pill:hover {
                border-color: ${CONFIG.themeColor} !important;
                color: ${CONFIG.themeColor} !important;
            }
            .cb-category-pill.active {
                background: ${CONFIG.themeColor} !important;
                color: white !important;
                border-color: ${CONFIG.themeColor} !important;
                box-shadow: 0 2px 6px ${rgbaColor(CONFIG.themeColor, 0.35)} !important;
            }
            .cb-category-chip {
                border-color: ${CONFIG.themeColor} !important;
            }
            .cb-mention-item.active {
                background: ${rgbaColor(CONFIG.themeColor, 0.1)} !important;
            }
        `;

        const existingStyles = document.querySelector('#chatbot-dynamic-styles');
        if (existingStyles) {
            existingStyles.textContent = dynamicCss;
        } else {
            const dynamicStyles = document.createElement('style');
            dynamicStyles.id = 'chatbot-dynamic-styles';
            dynamicStyles.textContent = dynamicCss;
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
                right: 24px;
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
            
            /* Draggable & Snappable Trigger Bubble */
            #chatbot-trigger-bubble {
                width: 60px;
                height: 60px;
                border-radius: 50%;
                background: linear-gradient(135deg, ${CONFIG.themeColor}, ${darkenColor(CONFIG.themeColor, 15)});
                color: white;
                border: none;
                cursor: grab;
                box-shadow: 0 8px 24px rgba(0, 0, 0, 0.16);
                display: flex;
                align-items: center;
                justify-content: center;
                transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
                outline: none;
                position: fixed;
                font-size: 28px;
                animation: cb-bubble-pop 0.22s cubic-bezier(0.175, 0.885, 0.32, 1.275);
                user-select: none;
                -webkit-user-select: none;
                touch-action: none;
                z-index: 1000000;
            }
            #chatbot-trigger-bubble.cb-dragging {
                cursor: grabbing !important;
                transform: scale(1.08) !important;
                box-shadow: 0 16px 36px rgba(0, 0, 0, 0.28) !important;
                transition: none !important;
            }
            #chatbot-trigger-bubble:hover:not(.cb-dragging) {
                transform: scale(1.05) translateY(-2px);
                box-shadow: 0 12px 30px rgba(0, 0, 0, 0.2);
            }
            #chatbot-trigger-bubble:active:not(.cb-dragging) {
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
                border: 1px solid rgba(0, 0, 0, 0.08);
                transform-origin: calc(100% - 30px) calc(100% + 40px);
            }
            .cb-pos-bottom-left #chatbot-window {
                transform-origin: 30px calc(100% + 40px);
            }
            #chatbot-window.cb-open {
                animation: cb-slide-in 0.28s cubic-bezier(0.16, 1, 0.3, 1) forwards;
            }
            #chatbot-window.cb-closing {
                animation: cb-slide-out 0.18s cubic-bezier(0.4, 0, 0.2, 1) forwards;
            }
            
            @keyframes cb-slide-in {
                from {
                    opacity: 0;
                    transform: scale(0.85);
                }
                to {
                    opacity: 1;
                    transform: scale(1);
                }
            }
            @keyframes cb-slide-out {
                from {
                    opacity: 1;
                    transform: scale(1);
                }
                to {
                    opacity: 0;
                    transform: scale(0.8);
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
                text-align: left;
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
                padding: 12px 18px;
                font-size: 14px;
                outline: none;
                transition: all 0.2s;
                color: #1e293b;
                resize: none;
                min-height: 46px;
                max-height: 140px;
                box-sizing: border-box;
                overflow-y: auto;
                scrollbar-width: none; /* Firefox */
                -ms-overflow-style: none; /* IE and Edge */
                line-height: 1.5;
                font-family: inherit;
            }
            #chatbot-input::-webkit-scrollbar {
                display: none; /* Chrome, Safari, Opera */
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

            /* Suggestions Skeleton Loading */
            .cb-skeleton-shimmer {
                background: linear-gradient(90deg, #f1f5f9 25%, #e2e8f0 50%, #f1f5f9 75%);
                background-size: 200% 100%;
                animation: cb-skeleton-wave 1.5s infinite ease-in-out;
            }
            .cb-suggestions-skeleton-title {
                height: 14px;
                width: 110px;
                border-radius: 4px;
                margin-bottom: 10px;
            }
            .cb-suggestion-skeleton-btn {
                height: 35px;
                border-radius: 8px;
                border: 1px solid #f1f5f9;
            }
            @keyframes cb-skeleton-wave {
                0% { background-position: 200% 0; }
                100% { background-position: -200% 0; }
            }

            /* Category Bar under Header (Horizontal scrollable pills) */
            .cb-category-bar {
                background: #f8fafc;
                padding: 8px 12px;
                display: flex;
                align-items: center;
                gap: 8px;
                border-bottom: 1px solid #e2e8f0;
                overflow-x: auto;
                white-space: nowrap;
                scrollbar-width: none; /* Firefox */
                -ms-overflow-style: none; /* IE/Edge */
                -webkit-overflow-scrolling: touch;
            }
            .cb-category-bar::-webkit-scrollbar {
                display: none; /* Chrome/Safari */
            }
            .cb-category-pill {
                display: inline-flex;
                align-items: center;
                gap: 5px;
                background: white;
                border: 1px solid #e2e8f0;
                border-radius: 16px;
                padding: 4px 10px;
                font-size: 12px;
                font-weight: 500;
                color: #475569;
                cursor: pointer;
                transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
                flex-shrink: 0;
                user-select: none;
                box-shadow: 0 1px 2px rgba(0,0,0,0.03);
            }
            .cb-category-pill:hover {
                border-color: ${CONFIG.themeColor};
                color: ${CONFIG.themeColor};
                background: #f1f5f9;
                transform: translateY(-1px);
            }
            .cb-category-pill.active {
                background: ${CONFIG.themeColor};
                color: white;
                border-color: ${CONFIG.themeColor};
                box-shadow: 0 2px 6px ${rgbaColor(CONFIG.themeColor, 0.35)};
            }
            .cb-category-pill-icon {
                font-size: 13px;
                line-height: 1;
            }
            .cb-category-pill-name {
                line-height: 1.2;
            }
            .cb-category-pill-clear {
                font-size: 10px;
                margin-left: 2px;
                opacity: 0.85;
                font-weight: bold;
                transition: opacity 0.15s;
            }
            .cb-category-pill-clear:hover {
                opacity: 1;
            }

            /* Mention Autocomplete Popup */
            .cb-mention-popup {
                position: absolute;
                bottom: 64px;
                left: 14px;
                right: 14px;
                max-height: 200px;
                overflow-y: auto;
                background: white;
                border-radius: 12px;
                box-shadow: 0 8px 24px rgba(0,0,0,0.14);
                border: 1px solid #e2e8f0;
                z-index: 1000;
            }
            .cb-mention-header {
                font-size: 11px;
                font-weight: 600;
                text-transform: uppercase;
                letter-spacing: 0.5px;
                color: #94a3b8;
                padding: 8px 12px 4px 12px;
                background: #f8fafc;
                border-bottom: 1px solid #f1f5f9;
            }
            .cb-mention-item {
                display: flex;
                align-items: center;
                gap: 10px;
                padding: 8px 12px;
                cursor: pointer;
                transition: background 0.15s;
                border-bottom: 1px solid #f8fafc;
            }
            .cb-mention-item:last-child {
                border-bottom: none;
            }
            .cb-mention-item:hover, .cb-mention-item.active {
                background: #f1f5f9;
            }
            .cb-mention-icon {
                font-size: 16px;
                flex-shrink: 0;
            }
            .cb-mention-info {
                display: flex;
                flex-direction: column;
                overflow: hidden;
            }
            .cb-mention-name {
                font-size: 13px;
                font-weight: 500;
                color: #1e293b;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }
            .cb-mention-slug {
                font-size: 11px;
                color: #64748b;
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
        const container = document.getElementById('chatbot-bubble-container');

        let isChatOpen = false;
        let isTransitioning = false;

        // Drag & Snap to 4 edges logic for trigger bubble
        const BUBBLE_SIZE = 60;
        const PADDING = 20;
        const BUBBLE_STORAGE_KEY = 'cb_bubble_position';

        let currentSnapX = 0;
        let currentSnapY = 0;
        let currentEdge = 'right';

        function applyBubblePosition(x, y, animate = false) {
            if (!trigger) return;
            trigger.style.transition = animate ? 'all 0.3s cubic-bezier(0.18, 0.89, 0.32, 1.28)' : 'none';
            trigger.style.left = `${x}px`;
            trigger.style.top = `${y}px`;
            trigger.style.right = 'auto';
            trigger.style.bottom = 'auto';
        }

        function snapToClosestEdge(curX, curY, animate = true) {
            const W = window.innerWidth;
            const H = window.innerHeight;
            const maxLeft = Math.max(PADDING, W - BUBBLE_SIZE - PADDING);
            const maxTop = Math.max(PADDING, H - BUBBLE_SIZE - PADDING);

            const distLeft = curX - PADDING;
            const distRight = maxLeft - curX;
            const distTop = curY - PADDING;
            const distBottom = maxTop - curY;

            const minDist = Math.min(distLeft, distRight, distTop, distBottom);
            let edge = 'right';
            let targetX = curX;
            let targetY = curY;

            if (minDist === distLeft) {
                edge = 'left';
                targetX = PADDING;
                targetY = Math.max(PADDING, Math.min(curY, maxTop));
            } else if (minDist === distRight) {
                edge = 'right';
                targetX = maxLeft;
                targetY = Math.max(PADDING, Math.min(curY, maxTop));
            } else if (minDist === distTop) {
                edge = 'top';
                targetY = PADDING;
                targetX = Math.max(PADDING, Math.min(curX, maxLeft));
            } else {
                edge = 'bottom';
                targetY = maxTop;
                targetX = Math.max(PADDING, Math.min(curX, maxLeft));
            }

            currentSnapX = targetX;
            currentSnapY = targetY;
            currentEdge = edge;

            applyBubblePosition(targetX, targetY, animate);

            try {
                localStorage.setItem(BUBBLE_STORAGE_KEY, JSON.stringify({
                    edge,
                    x: targetX,
                    y: targetY,
                    ratioX: W > 0 ? targetX / W : 1,
                    ratioY: H > 0 ? targetY / H : 1
                }));
            } catch (e) {}
        }

        // Initialize bubble position from localStorage or default
        function initBubblePosition() {
            if (!trigger) return;
            const W = window.innerWidth;
            const H = window.innerHeight;
            const maxLeft = Math.max(PADDING, W - BUBBLE_SIZE - PADDING);
            const maxTop = Math.max(PADDING, H - BUBBLE_SIZE - PADDING);

            let saved = null;
            try {
                const raw = localStorage.getItem(BUBBLE_STORAGE_KEY);
                if (raw) saved = JSON.parse(raw);
            } catch (e) {}

            if (saved && saved.edge) {
                currentEdge = saved.edge;
                let targetX = saved.x;
                let targetY = saved.y;

                if (saved.edge === 'left') {
                    targetX = PADDING;
                    targetY = saved.ratioY ? Math.max(PADDING, Math.min(saved.ratioY * H, maxTop)) : Math.max(PADDING, Math.min(saved.y, maxTop));
                } else if (saved.edge === 'right') {
                    targetX = maxLeft;
                    targetY = saved.ratioY ? Math.max(PADDING, Math.min(saved.ratioY * H, maxTop)) : Math.max(PADDING, Math.min(saved.y, maxTop));
                } else if (saved.edge === 'top') {
                    targetY = PADDING;
                    targetX = saved.ratioX ? Math.max(PADDING, Math.min(saved.ratioX * W, maxLeft)) : Math.max(PADDING, Math.min(saved.x, maxLeft));
                } else if (saved.edge === 'bottom') {
                    targetY = maxTop;
                    targetX = saved.ratioX ? Math.max(PADDING, Math.min(saved.ratioX * W, maxLeft)) : Math.max(PADDING, Math.min(saved.x, maxLeft));
                }
                currentSnapX = targetX;
                currentSnapY = targetY;
                applyBubblePosition(targetX, targetY, false);
            } else {
                if (CONFIG.position === 'bottom-left') {
                    snapToClosestEdge(PADDING, maxTop, false);
                } else {
                    snapToClosestEdge(maxLeft, maxTop, false);
                }
            }
        }

        initBubblePosition();

        window.addEventListener('resize', () => {
            if (trigger && trigger.style.display !== 'none') {
                snapToClosestEdge(currentSnapX, currentSnapY, false);
            }
        });

        // Pointer / Touch drag handling
        let isPointerDown = false;
        let isDragging = false;
        let startPointerX = 0;
        let startPointerY = 0;
        let startBubbleX = 0;
        let startBubbleY = 0;
        let ignoreClick = false;

        function onPointerStart(clientX, clientY) {
            isPointerDown = true;
            isDragging = false;
            startPointerX = clientX;
            startPointerY = clientY;
            const rect = trigger.getBoundingClientRect();
            startBubbleX = rect.left;
            startBubbleY = rect.top;
        }

        function onPointerMove(clientX, clientY, e) {
            if (!isPointerDown) return;
            const dx = clientX - startPointerX;
            const dy = clientY - startPointerY;

            if (!isDragging && Math.hypot(dx, dy) > 6) {
                isDragging = true;
                trigger.classList.add('cb-dragging');
                trigger.style.transition = 'none';
            }

            if (isDragging) {
                if (e && e.cancelable) e.preventDefault();
                const W = window.innerWidth;
                const H = window.innerHeight;
                let nextX = startBubbleX + dx;
                let nextY = startBubbleY + dy;

                nextX = Math.max(PADDING, Math.min(nextX, W - BUBBLE_SIZE - PADDING));
                nextY = Math.max(PADDING, Math.min(nextY, H - BUBBLE_SIZE - PADDING));

                trigger.style.left = `${nextX}px`;
                trigger.style.top = `${nextY}px`;
                trigger.style.right = 'auto';
                trigger.style.bottom = 'auto';
            }
        }

        function onPointerEnd() {
            if (!isPointerDown) return;
            isPointerDown = false;

            if (isDragging) {
                isDragging = false;
                trigger.classList.remove('cb-dragging');

                const rect = trigger.getBoundingClientRect();
                snapToClosestEdge(rect.left, rect.top, true);

                ignoreClick = true;
                setTimeout(() => {
                    ignoreClick = false;
                }, 200);
            }
        }

        if (trigger) {
            // Mouse listeners
            trigger.addEventListener('mousedown', (e) => {
                if (e.button !== 0) return;
                onPointerStart(e.clientX, e.clientY);

                const onMouseMove = (moveEvent) => {
                    onPointerMove(moveEvent.clientX, moveEvent.clientY, moveEvent);
                };

                const onMouseUp = () => {
                    document.removeEventListener('mousemove', onMouseMove);
                    document.removeEventListener('mouseup', onMouseUp);
                    onPointerEnd();
                };

                document.addEventListener('mousemove', onMouseMove);
                document.addEventListener('mouseup', onMouseUp);
            });

            // Touch listeners
            trigger.addEventListener('touchstart', (e) => {
                if (e.touches.length > 0) {
                    onPointerStart(e.touches[0].clientX, e.touches[0].clientY);
                }
            }, { passive: true });

            trigger.addEventListener('touchmove', (e) => {
                if (e.touches.length > 0) {
                    onPointerMove(e.touches[0].clientX, e.touches[0].clientY, e);
                }
            }, { passive: false });

            trigger.addEventListener('touchend', () => {
                onPointerEnd();
            });

            trigger.addEventListener('touchcancel', () => {
                onPointerEnd();
            });
        }

        function adjustContainerForOpenWindow() {
            if (!container) return;
            const curX = currentSnapX;
            const curY = currentSnapY;
            const isLeft = curX < window.innerWidth / 2;
            const isTop = curY < window.innerHeight / 2;

            if (isLeft) {
                container.style.left = '20px';
                container.style.right = 'auto';
                container.style.alignItems = 'flex-start';
            } else {
                container.style.right = '20px';
                container.style.left = 'auto';
                container.style.alignItems = 'flex-end';
            }

            if (isTop) {
                container.style.top = '20px';
                container.style.bottom = 'auto';
                if (windowDiv) {
                    windowDiv.style.marginBottom = '0';
                    windowDiv.style.marginTop = '0';
                    windowDiv.style.transformOrigin = isLeft ? 'top left' : 'top right';
                }
            } else {
                container.style.bottom = '20px';
                container.style.top = 'auto';
                if (windowDiv) {
                    windowDiv.style.marginBottom = '0';
                    windowDiv.style.marginTop = '0';
                    windowDiv.style.transformOrigin = isLeft ? 'bottom left' : 'bottom right';
                }
            }
        }

        function openChat() {
            if (isChatOpen || isTransitioning) return;
            isChatOpen = true;
            isTransitioning = true;
            adjustContainerForOpenWindow();
            windowDiv.classList.remove('cb-closing');
            windowDiv.classList.add('cb-open');
            windowDiv.style.display = 'flex';
            if (trigger) trigger.style.display = 'none';
            if (input) input.focus();
            renderCategoriesBar();
            setTimeout(() => {
                isTransitioning = false;
            }, 320);
        }

        function closeChat(e) {
            if (e) {
                e.preventDefault();
                e.stopPropagation();
            }
            if (isTransitioning) return;
            isChatOpen = false;
            isTransitioning = true;
            hideMentionPopup();
            windowDiv.classList.remove('cb-open');
            windowDiv.classList.add('cb-closing');

            setTimeout(() => {
                windowDiv.style.display = 'none';
                windowDiv.classList.remove('cb-closing');
                if (trigger) {
                    trigger.style.display = 'flex';
                    applyBubblePosition(currentSnapX, currentSnapY, false);
                }
                isTransitioning = false;
            }, 175);
        }

        function toggleChat() {
            if (windowDiv && (windowDiv.style.display !== 'none' || isChatOpen)) {
                closeChat();
            } else {
                openChat();
            }
        }

        if (trigger) {
            trigger.addEventListener('click', (e) => {
                if (ignoreClick) {
                    e.preventDefault();
                    e.stopPropagation();
                    return;
                }
                toggleChat();
            });
        }
        if (closeBtn) {
            closeBtn.addEventListener('click', closeChat);
            closeBtn.addEventListener('touchend', closeChat);
        }

        sendBtn.addEventListener('click', sendMessage);

        // Input listeners for @ mention detection & keyboard navigation
        input.addEventListener('input', () => {
            checkMentionTrigger();
        });

        input.addEventListener('keyup', (e) => {
            if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) {
                checkMentionTrigger();
            }
        });

        input.addEventListener('keydown', (e) => {
            // Mention popup navigation
            if (mentionPopup && mentionPopup.style.display === 'block' && filteredCategories.length > 0) {
                if (e.key === 'ArrowDown') {
                    e.preventDefault();
                    mentionSelectedIndex = (mentionSelectedIndex + 1) % filteredCategories.length;
                    updateMentionSelectedClass();
                    return;
                } else if (e.key === 'ArrowUp') {
                    e.preventDefault();
                    mentionSelectedIndex = (mentionSelectedIndex - 1 + filteredCategories.length) % filteredCategories.length;
                    updateMentionSelectedClass();
                    return;
                } else if (e.key === 'Enter' || e.key === 'Tab') {
                    e.preventDefault();
                    if (mentionSelectedIndex >= 0 && mentionSelectedIndex < filteredCategories.length) {
                        selectCategory(filteredCategories[mentionSelectedIndex]);
                    }
                    return;
                } else if (e.key === 'Escape') {
                    e.preventDefault();
                    hideMentionPopup();
                    return;
                }
            }

            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });

        // Hide mention popup when clicking outside
        document.addEventListener('click', (e) => {
            if (mentionPopup && mentionPopup.style.display === 'block') {
                if (!mentionPopup.contains(e.target) && e.target !== input) {
                    hideMentionPopup();
                }
            }
        });
    }

    // Helper functions for dynamic theme colors
    function darkenColor(hex, percent) {
        hex = hex.replace(/^\s*#|\s*$/g, '');
        if (hex.length == 3) hex = hex.replace(/(.)/g, '$1$1');
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
        if (hex.length == 3) hex = hex.replace(/(.)/g, '$1$1');
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
