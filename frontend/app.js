/* ==============================================================================
   DA-IICT Faculty AI Buddy - Frontend Logic (app.js)
   ============================================================================== */

document.addEventListener("DOMContentLoaded", () => {
    // DOM Elements
    const form = document.getElementById("input-form");
    const userInput = document.getElementById("user-input");
    const viewport = document.getElementById("chat-viewport");
    const welcomeScreen = document.getElementById("welcome-screen");
    const messagesContainer = document.getElementById("messages-container");
    const themeToggle = document.getElementById("theme-toggle");
    const clearChatBtn = document.getElementById("clear-chat");
    const suggestedLinks = document.querySelectorAll(".suggested-link");
    const promptCards = document.querySelectorAll(".prompt-card");

    // New DOM Elements for Chat History
    const chatHistoryList = document.getElementById("chat-history-list");
    const newChatBtn = document.getElementById("new-chat-btn");
    const clearHistoryBtn = document.getElementById("clear-history-btn");

    // Initialize state
    let chatSessions = [];
    let activeChatId = null;

    // Helper: Premium Markdown to HTML Renderer using Marked.js
    function renderMarkdown(text) {
        if (!text) return "";
        try {
            return marked.parse(text);
        } catch (e) {
            console.error("Marked parsing failed, falling back to raw text", e);
            return text;
        }
    }

    // Toggle Theme (Dark / Light)
    themeToggle.addEventListener("click", () => {
        const currentTheme = document.body.getAttribute("data-theme");
        const newTheme = currentTheme === "light" ? "dark" : "light";
        document.body.setAttribute("data-theme", newTheme);
        
        // Update Theme Icon
        const icon = themeToggle.querySelector("i");
        if (newTheme === "light") {
            icon.className = "fa-solid fa-sun";
        } else {
            icon.className = "fa-solid fa-moon";
        }
    });

    // Load chat history from localStorage
    function loadChatHistory() {
        const stored = localStorage.getItem("dau_buddy_chats");
        if (stored) {
            try {
                chatSessions = JSON.parse(stored);
            } catch (e) {
                console.error("Error parsing stored chat sessions", e);
                chatSessions = [];
            }
        }
        
        // Select active chat or create a fresh one if empty
        if (chatSessions.length > 0) {
            activeChatId = chatSessions[0].id;
        } else {
            createNewChat();
        }
        
        renderChatHistoryList();
        loadActiveChat();
    }

    // Save chat history to localStorage
    function saveChatHistory() {
        localStorage.setItem("dau_buddy_chats", JSON.stringify(chatSessions));
    }

    // Create a new chat session
    function createNewChat() {
        // If there's already an active empty chat, just reuse it
        const currentActive = chatSessions.find(s => s.id === activeChatId);
        if (currentActive && currentActive.messages.length === 0) {
            return;
        }

        const newId = Date.now().toString();
        const newSession = {
            id: newId,
            title: "New Chat",
            messages: [],
            timestamp: Date.now()
        };

        chatSessions.unshift(newSession);
        activeChatId = newId;
        saveChatHistory();
        renderChatHistoryList();
        loadActiveChat();
        closeMobileSidebar();
    }

    // Render left sidebar chat history items
    function renderChatHistoryList() {
        chatHistoryList.innerHTML = "";
        
        if (chatSessions.length === 0) {
            const emptyEl = document.createElement("div");
            emptyEl.style.padding = "16px";
            emptyEl.style.textAlign = "center";
            emptyEl.style.color = "var(--text-muted)";
            emptyEl.style.fontSize = "12px";
            emptyEl.textContent = "No past chats";
            chatHistoryList.appendChild(emptyEl);
            return;
        }

        chatSessions.forEach(session => {
            const item = document.createElement("div");
            item.className = `chat-history-item${session.id === activeChatId ? " active" : ""}`;
            item.setAttribute("data-id", session.id);

            const mainDiv = document.createElement("div");
            mainDiv.className = "chat-item-main";
            
            const icon = document.createElement("i");
            icon.className = "fa-regular fa-message";
            
            const titleSpan = document.createElement("span");
            titleSpan.className = "chat-item-title";
            titleSpan.textContent = session.title || "New Chat";
            
            mainDiv.appendChild(icon);
            mainDiv.appendChild(titleSpan);

            const deleteBtn = document.createElement("button");
            deleteBtn.className = "delete-chat-btn";
            deleteBtn.title = "Delete Chat";
            deleteBtn.innerHTML = '<i class="fa-solid fa-trash-can"></i>';
            
            // Delete chat click handler
            deleteBtn.addEventListener("click", (e) => {
                e.stopPropagation(); // Avoid selecting the chat when deleting
                deleteChat(session.id);
            });

            // Select chat click handler
            item.addEventListener("click", () => {
                selectChat(session.id);
            });

            item.appendChild(mainDiv);
            item.appendChild(deleteBtn);
            chatHistoryList.appendChild(item);
        });
    }

    // Select a specific chat session
    function selectChat(id) {
        if (activeChatId === id) return;
        activeChatId = id;
        renderChatHistoryList();
        loadActiveChat();
        closeMobileSidebar();
    }

    // Load active chat messages into the viewport
    function loadActiveChat() {
        messagesContainer.innerHTML = "";

        const activeSession = chatSessions.find(s => s.id === activeChatId);
        if (!activeSession || activeSession.messages.length === 0) {
            welcomeScreen.style.display = "flex";
            welcomeScreen.style.flexDirection = "column";
            welcomeScreen.style.alignItems = "center";
            welcomeScreen.style.justifyContent = "center";
            return;
        }

        welcomeScreen.style.display = "none";
        activeSession.messages.forEach((msg, idx) => {
            appendMessageHTML(msg.sender, msg.text, idx);
        });
        scrollToBottom();
    }

    // Delete a specific chat session
    function deleteChat(id) {
        const index = chatSessions.findIndex(s => s.id === id);
        if (index === -1) return;

        chatSessions.splice(index, 1);
        saveChatHistory();

        if (activeChatId === id) {
            if (chatSessions.length > 0) {
                activeChatId = chatSessions[0].id;
            } else {
                activeChatId = null;
                createNewChat();
                return;
            }
        }
        
        renderChatHistoryList();
        loadActiveChat();
    }

    // Clear all history
    function clearAllHistory() {
        if (confirm("Are you sure you want to delete all chat history? This cannot be undone.")) {
            chatSessions = [];
            activeChatId = null;
            localStorage.removeItem("dau_buddy_chats");
            createNewChat();
        }
    }

    // Clear Active Chat contents (from top right header action)
    clearChatBtn.addEventListener("click", () => {
        const activeSession = chatSessions.find(s => s.id === activeChatId);
        if (activeSession && activeSession.messages.length > 0) {
            if (confirm("Clear messages in this chat session?")) {
                activeSession.messages = [];
                activeSession.title = "New Chat";
                saveChatHistory();
                renderChatHistoryList();
                loadActiveChat();
            }
        }
    });

    // Submit user question
    async function handleSend(text) {
        if (!text.trim()) return;

        // Hide welcome screen
        welcomeScreen.style.display = "none";

        // Get or create active session
        let activeSession = chatSessions.find(s => s.id === activeChatId);
        if (!activeSession) {
            createNewChat();
            activeSession = chatSessions.find(s => s.id === activeChatId);
        }

        // Generate title if it's the first message
        if (activeSession.messages.length === 0) {
            const shortTitle = text.length > 28 ? text.substring(0, 25) + "..." : text;
            activeSession.title = shortTitle;
            renderChatHistoryList();
        }

        // Append to state history and save
        activeSession.messages.push({ sender: "user", text: text });
        saveChatHistory();

        // 1. Render User Message
        appendMessageHTML("user", text, activeSession.messages.length - 1);
        userInput.value = "";
        scrollToBottom();

        // 2. Render AI Typing Indicator
        const typingIndicator = appendTypingIndicator();
        scrollToBottom();

        // 3. Perform Server API Call
        try {
            const response = await fetch("/api/chat", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({ 
                    message: text,
                    history: activeSession.messages
                })
            });

            if (!response.ok) {
                throw new Error("Server connection issues");
            }

            const data = await response.json();
            
            // Remove typing indicator
            typingIndicator.remove();

            // Append to state history and save
            activeSession.messages.push({ sender: "ai", text: data.response });
            saveChatHistory();

            // Render AI response
            appendMessageHTML("ai", data.response, activeSession.messages.length - 1);
        } catch (error) {
            typingIndicator.remove();
            
            const errorMsg = `⚠️ Sorry, I encountered an error communicating with the database: ${error.message}`;
            activeSession.messages.push({ sender: "ai", text: errorMsg });
            saveChatHistory();
            
            appendMessageHTML("ai", errorMsg, activeSession.messages.length - 1);
        }
        
        scrollToBottom();
    }

    // Append Message Row to Container (UI rendering only)
    function appendMessageHTML(sender, text, index) {
        const row = document.createElement("div");
        row.className = `msg-row ${sender}`;
        if (sender === "user" && typeof index === "number") {
            row.setAttribute("data-idx", index);
        }

        const avatar = document.createElement("div");
        avatar.className = "avatar";
        avatar.innerHTML = sender === "user" ? '<i class="fa-solid fa-user"></i>' : '<i class="fa-solid fa-graduation-cap"></i>';

        const wrapper = document.createElement("div");
        wrapper.className = "bubble-wrapper";

        const bubble = document.createElement("div");
        bubble.className = "bubble";
        
        if (sender === "user") {
            bubble.textContent = text;
            
            // Create user bubble actions (Copy and Edit buttons) below the bubble
            const actions = document.createElement("div");
            actions.className = "bubble-actions";
            
            const copyBtn = document.createElement("button");
            copyBtn.className = "bubble-action-btn copy-btn";
            copyBtn.title = "Copy prompt";
            copyBtn.innerHTML = '<i class="fa-solid fa-copy"></i>';
            copyBtn.addEventListener("click", (e) => {
                e.stopPropagation();
                const copyText = () => {
                    copyBtn.innerHTML = '<i class="fa-solid fa-check"></i>';
                    copyBtn.style.color = "#10b981";
                    setTimeout(() => {
                        copyBtn.innerHTML = '<i class="fa-solid fa-copy"></i>';
                        copyBtn.style.color = "";
                    }, 2000);
                };
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    navigator.clipboard.writeText(text).then(copyText);
                } else {
                    const textarea = document.createElement("textarea");
                    textarea.value = text;
                    textarea.style.position = "fixed";
                    document.body.appendChild(textarea);
                    textarea.select();
                    try {
                        document.execCommand("copy");
                        copyText();
                    } catch (err) {
                        console.error("Fallback copy failed", err);
                    }
                    document.body.removeChild(textarea);
                }
            });

            const editBtn = document.createElement("button");
            editBtn.className = "bubble-action-btn edit-btn";
            editBtn.title = "Edit prompt";
            editBtn.innerHTML = '<i class="fa-solid fa-pen-to-square"></i>';
            editBtn.addEventListener("click", (e) => {
                e.stopPropagation();
                
                // Switch bubble to Edit Mode (in-place text editing)
                bubble.innerHTML = "";
                
                const textarea = document.createElement("textarea");
                textarea.className = "edit-textarea";
                textarea.value = text;
                
                const btnContainer = document.createElement("div");
                btnContainer.className = "edit-bubble-actions";
                
                const cancelBtn = document.createElement("button");
                cancelBtn.className = "edit-action-btn cancel";
                cancelBtn.textContent = "Cancel";
                cancelBtn.addEventListener("click", (e2) => {
                    e2.stopPropagation();
                    loadActiveChat(); // Simply reload the active chat to restore state
                });
                
                const submitBtn = document.createElement("button");
                submitBtn.className = "edit-action-btn submit";
                submitBtn.textContent = "Save & Submit";
                submitBtn.addEventListener("click", async (e2) => {
                    e2.stopPropagation();
                    const newText = textarea.value.trim();
                    if (!newText) return;
                    
                    const activeSession = chatSessions.find(s => s.id === activeChatId);
                    if (!activeSession) return;
                    
                    // Slice session history to exclude this message and all subsequent messages
                    if (typeof index === "number") {
                        activeSession.messages = activeSession.messages.slice(0, index);
                    }
                    
                    // Clear and re-render the chat window to remove subsequent messages
                    loadActiveChat();
                    
                    // Triggers the standard sending pipeline with the newly edited prompt
                    handleSend(newText);
                });

                // Keydown listener to submit on Enter key (without Shift)
                textarea.addEventListener("keydown", (eKey) => {
                    if (eKey.key === "Enter" && !eKey.shiftKey) {
                        eKey.preventDefault();
                        submitBtn.click();
                    }
                });
                
                btnContainer.appendChild(cancelBtn);
                btnContainer.appendChild(submitBtn);
                
                bubble.appendChild(textarea);
                bubble.appendChild(btnContainer);
                
                // Focus textarea and position cursor at the end
                textarea.focus();
                textarea.setSelectionRange(textarea.value.length, textarea.value.length);
            });

            actions.appendChild(copyBtn);
            actions.appendChild(editBtn);
            
            wrapper.appendChild(bubble);
            wrapper.appendChild(actions);
        } else {
            bubble.innerHTML = renderMarkdown(text);
            
            // Create AI bubble actions (Copy response) below the bubble
            const actions = document.createElement("div");
            actions.className = "bubble-actions";
            
            const copyBtn = document.createElement("button");
            copyBtn.className = "bubble-action-btn copy-btn";
            copyBtn.title = "Copy response";
            copyBtn.innerHTML = '<i class="fa-solid fa-copy"></i>';
            copyBtn.addEventListener("click", (e) => {
                e.stopPropagation();
                const copyText = () => {
                    copyBtn.innerHTML = '<i class="fa-solid fa-check"></i>';
                    copyBtn.style.color = "#10b981";
                    setTimeout(() => {
                        copyBtn.innerHTML = '<i class="fa-solid fa-copy"></i>';
                        copyBtn.style.color = "";
                    }, 2000);
                };
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    navigator.clipboard.writeText(text).then(copyText);
                } else {
                    const textarea = document.createElement("textarea");
                    textarea.value = text;
                    textarea.style.position = "fixed";
                    document.body.appendChild(textarea);
                    textarea.select();
                    try {
                        document.execCommand("copy");
                        copyText();
                    } catch (err) {
                        console.error("Fallback copy failed", err);
                    }
                    document.body.removeChild(textarea);
                }
            });
            
            actions.appendChild(copyBtn);
            wrapper.appendChild(bubble);
            wrapper.appendChild(actions);
        }

        row.appendChild(avatar);
        row.appendChild(wrapper);
        messagesContainer.appendChild(row);
    }

    // Append Typing Indicator Row
    function appendTypingIndicator() {
        const row = document.createElement("div");
        row.className = "msg-row ai";

        const avatar = document.createElement("div");
        avatar.className = "avatar";
        avatar.innerHTML = '<i class="fa-solid fa-graduation-cap"></i>';

        const wrapper = document.createElement("div");
        wrapper.className = "bubble-wrapper";

        const bubble = document.createElement("div");
        bubble.className = "bubble";
        
        const dots = document.createElement("div");
        dots.className = "typing-dots";
        dots.innerHTML = "<span></span><span></span><span></span>";
        
        bubble.appendChild(dots);
        wrapper.appendChild(bubble);
        row.appendChild(avatar);
        row.appendChild(wrapper);
        messagesContainer.appendChild(row);
        
        return row;
    }

    // Smooth scroll chat to bottom
    function scrollToBottom() {
        viewport.scrollTo({
            top: viewport.scrollHeight,
            behavior: "smooth"
        });
    }

    // Form Event Listener
    form.addEventListener("submit", (e) => {
        e.preventDefault();
        const text = userInput.value;
        handleSend(text);
    });

    // Suggested Actions / Prompts Click Event (Welcome screen prompt cards)
    promptCards.forEach(card => {
        card.addEventListener("click", () => {
            const prompt = card.getAttribute("data-prompt");
            handleSend(prompt);
        });
    });

    // New Chat button event
    newChatBtn.addEventListener("click", createNewChat);

    // Clear all history button event
    clearHistoryBtn.addEventListener("click", clearAllHistory);

    // Initialize/Load chat history
    loadChatHistory();

    // Mobile Responsive Sidebar Navigation Toggle
    const sidebarToggle = document.getElementById("sidebar-toggle");
    const sidebar = document.getElementById("sidebar") || document.querySelector(".sidebar");
    
    // Inject sidebar overlay dynamically into DOM
    const overlay = document.createElement("div");
    overlay.className = "sidebar-overlay";
    overlay.id = "sidebar-overlay";
    document.body.appendChild(overlay);

    if (sidebarToggle) {
        const handleToggle = (e) => {
            e.preventDefault();
            e.stopPropagation();
            const isMobile = window.innerWidth <= 768;
            if (isMobile) {
                sidebar.classList.toggle("open");
                overlay.classList.toggle("active");
                sidebar.classList.remove("collapsed");
            } else {
                sidebar.classList.toggle("collapsed");
                sidebar.classList.remove("open");
                overlay.classList.remove("active");
            }
        };
        sidebarToggle.addEventListener("click", handleToggle);
        sidebarToggle.addEventListener("touchstart", handleToggle, { passive: false });
    }

    overlay.addEventListener("click", closeMobileSidebar);
    overlay.addEventListener("touchstart", (e) => {
        e.preventDefault();
        closeMobileSidebar();
    }, { passive: false });

    function closeMobileSidebar() {
        if (sidebar && sidebar.classList.contains("open")) {
            sidebar.classList.remove("open");
        }
        if (overlay && overlay.classList.contains("active")) {
            overlay.classList.remove("active");
        }
    }
});
