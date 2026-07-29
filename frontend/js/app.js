// Global callback for Google Sign-In, declared outside DOMContentLoaded to ensure it's available for GSI
window.handleCredentialResponse = (response) => {
    if (window.processLogin) {
        window.processLogin(response);
    } else {
        // Fallback in case the callback fires before DOMContentLoaded completes
        document.addEventListener("DOMContentLoaded", () => {
            if (window.processLogin) window.processLogin(response);
        });
    }
};

document.addEventListener("DOMContentLoaded", () => {
    // â”€â”€ Google OAuth & Session Management â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    const loginOverlay = document.getElementById("login-overlay");
    const appContainer = document.getElementById("app-container");
    const loginError = document.getElementById("login-error");
    const welcomeName = document.getElementById("welcome-name");
    const logoutBtn = document.getElementById("logout-btn");
    const apiKeyInput = document.getElementById("api-key-input");
    const regenerateBtn = document.getElementById("regenerate-key-btn");
    const configCode = document.getElementById("claude-config-code");
    const cursorConfigCode = document.getElementById("cursor-config-code");
    const dropdownName = document.getElementById("dropdown-name");
    const dropdownEmail = document.getElementById("dropdown-email");
    const dropdownAvatar = document.getElementById("dropdown-avatar");
    const navProfileTrigger = document.getElementById("nav-profile-trigger");
    const dropdownRole = document.getElementById("dropdown-role");
    const profileDropdown = document.getElementById("profile-dropdown");
    const profileContainer = document.getElementById("profile-container");

    const landingProfileContainer = document.getElementById("landing-profile-container");
    const landingProfileTrigger = document.getElementById("landing-profile-trigger");
    const landingProfileDropdown = document.getElementById("landing-profile-dropdown");
    const landingDropdownAvatar = document.getElementById("landing-dropdown-avatar");
    const landingDropdownName = document.getElementById("landing-dropdown-name");
    const landingDropdownEmail = document.getElementById("landing-dropdown-email");
    const landingDropdownRole = document.getElementById("landing-dropdown-role");
    const landingLogoutBtn = document.getElementById("landing-logout-btn");


    function setApiKeyValue(val) {
        if (apiKeyInput) {
            if (apiKeyInput) apiKeyInput.value = val;
        }
    }

    function updateMaintainerDashboardVisibility(role) {
        const dashboardBtn = document.getElementById("nav-dashboard-btn");
        if (dashboardBtn) {
            if (role && role.includes("Maintainer")) {
                dashboardBtn.style.display = "flex";
            } else {
                dashboardBtn.style.display = "none";
            }
        }
    }

    async function checkExistingKey(credential) {
        // [Lines truncated for replace block; we will replace from the start of the file down to the old handleCredentialResponse]
        try {
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 10000);
            const response = await fetch("/api/me", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ credential: credential }),
                signal: controller.signal
            });
            clearTimeout(timeoutId);
            if (response.ok) {
                const data = await response.json();

                // ALWAYS update the role if the API provides it
                if (dropdownRole || landingDropdownRole) {
                    const role = data.role || "User";
                    if (dropdownRole) dropdownRole.textContent = role;
                    if (landingDropdownRole) landingDropdownRole.textContent = role;
                    const authData = JSON.parse(localStorage.getItem("dau_buddy_auth") || "{}");
                    authData.role = role;
                    localStorage.setItem("dau_buddy_auth", JSON.stringify(authData));
                    updateMaintainerDashboardVisibility(role);
                }

                if (data.has_key) {
                    const key = data.api_key;
                    if (key) {
                        if (apiKeyInput && (apiKeyInput.value === "Loading..." || apiKeyInput.value.includes("Please"))) {
                            setApiKeyValue(key);
                            updateConfigSnippet(key);
                        }
                    }
                    if (data.key_prefix) {
                        const authData = JSON.parse(localStorage.getItem("dau_buddy_auth") || "{}");
                        authData.key_prefix = data.key_prefix;
                        localStorage.setItem("dau_buddy_auth", JSON.stringify(authData));
                    }
                    return { hasKey: true, prefix: data.key_prefix };
                }
            } else if (response.status === 429) {
                return { rateLimited: true };
            } else if (response.status === 401) {
                // Token expired or invalid
                localStorage.removeItem("dau_buddy_auth");
                window.location.reload();
            }
        } catch (e) {
            console.error("Error checking key", e);
        }
        return false;
    }

    async function generateKey(credential, regenerate = false) {
        try {
            setApiKeyValue("Generating...");
            if (regenerateBtn) {
                regenerateBtn.disabled = true;
                regenerateBtn.textContent = "Generating...";
            }
            
            if (!credential) {
                alert("Error: Missing Google credential in frontend. Please login again.");
                return;
            }

            const endpoint = regenerate ? "/api/regenerate-key" : "/api/generate-key";
            const response = await fetch(endpoint, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ credential: credential })
            });
            if (response.ok) {
                const data = await response.json();
                const key = data.api_key;
                
                // Show modal with new key
                const newKeyModal = document.getElementById("new-key-modal");
                const newKeyInput = document.getElementById("new-key-input");
                if (newKeyModal && newKeyInput) {
                    newKeyInput.value = key;
                    newKeyModal.style.display = "flex";
                }
                
                // Mask the key on main UI
                const maskedKey = (data.key_prefix || key.substring(0, 14)) + "â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢";
                setApiKeyValue(maskedKey);

                updateConfigSnippet(maskedKey);
                if (dropdownRole || landingDropdownRole) {
                    const role = data.role || "User";
                    if (dropdownRole) dropdownRole.textContent = role;
                    if (landingDropdownRole) landingDropdownRole.textContent = role;

                    const updatedAuth = JSON.parse(localStorage.getItem("dau_buddy_auth") || "{}");
                    updatedAuth.role = role;
                    localStorage.setItem("dau_buddy_auth", JSON.stringify(updatedAuth));
                    updateMaintainerDashboardVisibility(role);
                }
            } else {
                if (response.status === 401) {
                    alert("Session expired. Please login again.");
                    localStorage.removeItem("dau_buddy_auth");
                    window.location.reload();
                    return;
                }
                const err = await response.json();
                const errMsg = (typeof err.detail === 'object') ? JSON.stringify(err.detail) : (err.detail || "Error generating key.");
                setApiKeyValue(errMsg);
                alert("API Error: " + errMsg);
            }
        } catch (e) {
            console.error(e);
            setApiKeyValue("Error generating key.");
            alert("Frontend Error: " + e.message);
        } finally {
            if (regenerateBtn) {
                regenerateBtn.disabled = false;
                regenerateBtn.textContent = "Regenerate Key";
            }
        }
    }

    let pythonPath = "python";
    let projectPath = "E:\\\\MCP Project";

    // Fetch local paths dynamically on startup
    fetch("/api/config-info")
        .then(res => res.json())
        .then(data => {
            if (data.python_path) pythonPath = data.python_path;
            if (data.project_path) projectPath = data.project_path;
            // If there's an existing placeholder, update the snippet
            if (apiKeyInput && apiKeyInput.value && !apiKeyInput.value.startsWith("Generating") && !apiKeyInput.value.startsWith("Error")) {
                updateConfigSnippet(apiKeyInput.value);
            }
        })
        .catch(err => console.error("Error fetching config info:", err));


    function updateConfigSnippet(key) {
        // Escape backslashes for JSON representation
        const escapedPythonPath = pythonPath.replace(/\\/g, "\\\\");
        const escapedProjectPath = projectPath.replace(/\\/g, "\\\\");
        const baseUrl = window.location.origin + "/mcp/sse";

        // Claude Desktop (Stdio)
        const claudeText = `{
  "mcpServers": {
    "DAU Buddy": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "${baseUrl}",
        "--allow-http",
        "--transport",
        "sse-only",
        "--header",
        "Authorization:\${AUTH_HEADER}",
        "--header",
        "X-Client-Name:Claude"
      ],
      "env": {
        "AUTH_HEADER": "Bearer <YOUR_API_KEY>"
      }
    }
  }
}`;
        if (configCode) configCode.textContent = claudeText;

        // Cursor / Windsurf (HTTP/SSE)
        const cursorText = `{
  "mcpServers": {
    "DAU Buddy": {
      "type": "sse",
      "url": "${baseUrl}",
      "headers": {
        "Authorization": "Bearer <YOUR_API_KEY>",
        "X-Client-Name": "Cursor/Windsurf"
      }
    }
  }
}`;
        if (cursorConfigCode) {
            if (cursorConfigCode) cursorConfigCode.textContent = cursorText;
        }

        // OpenCode (HTTP/SSE) - Uses "remote" type
        const opencodeText = `{
  "mcpServers": {
    "DAU Buddy": {
      "type": "remote",
      "url": "${baseUrl}",
      "headers": {
        "Authorization": "Bearer <YOUR_API_KEY>",
        "X-Client-Name": "OpenCode"
      }
    }
  }
}`;
        const opencodeConfigCode = document.getElementById("opencode-config-code");
        if (opencodeConfigCode) {
            opencodeConfigCode.textContent = opencodeText;
        }

        const connectorsUrlDisplay = document.getElementById("connectors-url-display");
        if (connectorsUrlDisplay) {
            connectorsUrlDisplay.textContent = baseUrl;
        }
    }

    let currentCredential = null;
    let currentEmail = null;

    async function showWelcomeScreen(name, email, picture, credential = null, cachedKey = null, autoShowDashboard = true) {
        currentEmail = email;
        if (credential) currentCredential = credential;

        if (autoShowDashboard) {
            // Hide landing page and login overlay
            const landingView = document.getElementById("landing-view");
            if (landingView) landingView.style.display = "none";

            if (loginOverlay) if (loginOverlay) loginOverlay.style.opacity = "0";
            if (loginOverlay) if (loginOverlay) loginOverlay.style.display = "none";
            
          setTimeout(() => {
            window.location.href = "/chat";
        }, 1500);
        }

        let displayName = name || "User";
        if (name) {
            // If the display name is purely numeric (e.g. "2025 12063"), use the email local part instead
            const firstName = name.split(" ")[0];
            displayName = /^\d+$/.test(firstName) ? email.split("@")[0] : firstName;
        }
        if (welcomeName) welcomeName.textContent = `Welcome, ${displayName}!`;
        if (dropdownName) dropdownName.textContent = displayName;
        if (dropdownEmail) dropdownEmail.textContent = email;
        if (landingDropdownName) landingDropdownName.textContent = displayName;
        if (landingDropdownEmail) landingDropdownEmail.textContent = email;

        if (picture) {
            if (dropdownAvatar) dropdownAvatar.src = picture;
            if (navProfileTrigger) navProfileTrigger.src = picture;
            if (landingDropdownAvatar) landingDropdownAvatar.src = picture;
            if (landingProfileTrigger) landingProfileTrigger.src = picture;
        }

        // Determine role synchronously from email
        if ((dropdownRole || landingDropdownRole) && email) {
            let role = "User";
            if (email.endsWith("@dau.ac.in")) {
                const localPart = email.split("@")[0];
                if (/^\d+$/.test(localPart)) {
                    role = "Student";
                } else {
                    role = "Faculty/Staff";
                }
            }
            // Temporarily set it until API overrides, but don't assume Maintainer here
            if (dropdownRole) dropdownRole.textContent = role;
            if (landingDropdownRole) landingDropdownRole.textContent = role;
            updateMaintainerDashboardVisibility(role);
        }

        let activeKey = cachedKey;

        // Only use activeKey if it's an actual hex key
        if (activeKey && activeKey !== "Loading..." && activeKey !== "No API Key Generated" && activeKey !== "No key exists. Please generate.") {
            setApiKeyValue(activeKey);
            updateConfigSnippet(activeKey);
            if (regenerateBtn) regenerateBtn.textContent = "Regenerate Key";

            // Restore role if saved
            const authData = JSON.parse(localStorage.getItem("dau_buddy_auth") || "{}");
            if (authData.role && (dropdownRole || landingDropdownRole)) {
                if (dropdownRole) dropdownRole.textContent = authData.role;
                if (landingDropdownRole) landingDropdownRole.textContent = authData.role;
                updateMaintainerDashboardVisibility(authData.role);
            }

            // Sync status/role in background if we have credential
            if (currentCredential) {
                checkExistingKey(currentCredential);
            }
        } else if (currentCredential) {
            const result = await checkExistingKey(currentCredential);
            if (result && result.rateLimited) {
                setApiKeyValue("Rate limit exceeded. Please wait a minute.");
                if (regenerateBtn) regenerateBtn.textContent = "Wait & Refresh";
                updateConfigSnippet("YOUR_API_KEY_HERE");
            } else {
                const hasKey = result && result.hasKey;
                if (!hasKey) {
                    setApiKeyValue("No API Key Generated");
                    if (regenerateBtn) regenerateBtn.textContent = "Generate Key";
                    updateConfigSnippet("YOUR_API_KEY_HERE");
                } else {
                    if (regenerateBtn) {
                        regenerateBtn.textContent = "Regenerate Key";
                    }
                    if (result.prefix) {
                        const maskedKey = result.prefix + "â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢";
                        setApiKeyValue(maskedKey);
                        updateConfigSnippet(maskedKey);
                    } else {
                        setApiKeyValue("Key exists but is not cached. Please regenerate.");
                        updateConfigSnippet("YOUR_API_KEY_HERE");
                    }
                }
            }
        } else {
            // Should not happen, but fallback
            setApiKeyValue("Please Login Again");
            if (dropdownRole) dropdownRole.textContent = "";
            if (landingDropdownRole) landingDropdownRole.textContent = "";
        }

        if (regenerateBtn) {
            regenerateBtn.onclick = async () => {
                if (regenerateBtn.textContent.includes("Wait & Refresh")) {
                    window.location.reload();
                    return;
                }
                const isRegenerating = regenerateBtn.textContent.includes("Regenerate") || regenerateBtn.textContent.includes("Generating");
                await generateKey(currentCredential, isRegenerating);
            };
        }
    }
    // Handle URL parameters for view routing from external pages (like docs.html)
    const urlParams = new URLSearchParams(window.location.search);
    const viewParam = urlParams.get('view');
    if (viewParam === 'landing' || viewParam === 'dashboard') {
        localStorage.setItem("dau_buddy_view", viewParam);
        // Clean up the URL so refresh works normally
        window.history.replaceState({}, document.title, window.location.pathname);
    } else if (viewParam === 'login') {
        localStorage.setItem("dau_buddy_view", "landing");
        window.history.replaceState({}, document.title, window.location.pathname);
        // Wait just a tiny bit for the UI to be ready
        setTimeout(() => {
            if (window.openLoginModal) {
                window.openLoginModal();
            } else {
                // Fallback in case script order is weird
                setTimeout(() => {
                    if (window.openLoginModal) window.openLoginModal();
                }, 300);
            }
        }, 100);
    }

    // Check if user is already logged in
    const storedSession = localStorage.getItem("dau_buddy_auth");
    if (storedSession) {
        try {
            const authData = JSON.parse(storedSession);
            if (authData.email && authData.credential) {
                // Determine which view to show based on last state
                const currentView = localStorage.getItem("dau_buddy_view");
                const shouldShowDashboard = (currentView === "dashboard");

                if (shouldShowDashboard && window.location.pathname === "/") {
                    window.location.href = "/chat";
                    return;
                }

                // Valid session exists, configure UI
                showWelcomeScreen(authData.name, authData.email, authData.picture, authData.credential, authData.api_key, false);
                
                // Update landing page buttons to indicate they lead to the dashboard
                const btnSignIn = document.getElementById("nav-signin-btn");
                const btnDocsLogin = document.getElementById("docs-login-btn");
                const btnGetStarted = document.getElementById("hero-get-started-btn");
                if (btnSignIn) {
                    btnSignIn.innerHTML = '<i class="fa-solid fa-code"></i> Dashboard';
                    btnSignIn.className = 'nav-docs-btn';
                    btnSignIn.onclick = function(e) { e.preventDefault(); window.location.href = '/api-keys'; };
                    if (landingProfileContainer) landingProfileContainer.style.display = "block";
                }
                if (btnDocsLogin) {
                    btnDocsLogin.innerHTML = '<i class="fa-solid fa-code"></i> Dashboard';
                    btnDocsLogin.className = 'nav-docs-btn';
                    btnDocsLogin.style.display = 'inline-block';
                    btnDocsLogin.onclick = function(e) { e.preventDefault(); window.location.href = '/api-keys'; };
                    if (landingProfileContainer) landingProfileContainer.style.display = "block";
                }
                if (btnGetStarted) btnGetStarted.textContent = "Go to Dashboard";
            }
        } catch (e) {
            console.error("Invalid auth session data", e);
            localStorage.removeItem("dau_buddy_auth");
        }
    }

    // Global callback for Google Sign-In
    window.processLogin = (response) => {
        try {
            // Decode JWT token payload (middle part)
            const payloadBase64 = response.credential.split('.')[1];
            const decodedPayload = JSON.parse(atob(payloadBase64.replace(/-/g, '+').replace(/_/g, '/')));

            const email = decodedPayload.email;
            const currentLoginError = document.getElementById("login-error");
            const currentLoginOverlay = document.getElementById("login-overlay");

            if (email) {
                // Successful login
                localStorage.setItem("dau_buddy_auth", JSON.stringify({
                    email: email,
                    name: decodedPayload.name,
                    picture: decodedPayload.picture,
                    credential: response.credential
                }));
                if (currentLoginError) currentLoginError.style.display = "none";
                
                // Update landing page buttons immediately
                const btnSignIn = document.getElementById("nav-signin-btn");
                const btnDocsLogin = document.getElementById("docs-login-btn");
                const btnGetStarted = document.getElementById("hero-get-started-btn");
                if (btnSignIn) {
                    btnSignIn.innerHTML = '<i class="fa-solid fa-code"></i> Dashboard';
                    btnSignIn.className = 'nav-docs-btn';
                    btnSignIn.onclick = function(e) { e.preventDefault(); window.location.href = '/api-keys'; };
                    if (landingProfileContainer) landingProfileContainer.style.display = "block";
                }
                if (btnDocsLogin) {
                    btnDocsLogin.innerHTML = '<i class="fa-solid fa-code"></i> Dashboard';
                    btnDocsLogin.className = 'nav-docs-btn';
                    btnDocsLogin.style.display = 'inline-block';
                    btnDocsLogin.onclick = function(e) { e.preventDefault(); window.location.href = '/api-keys'; };
                    if (landingProfileContainer) landingProfileContainer.style.display = "block";
                }
                if (btnGetStarted) btnGetStarted.textContent = "Go to Dashboard";

                // Fade out overlay
                if (currentLoginOverlay) currentLoginOverlay.style.opacity = "0";
                setTimeout(() => {
                    if (currentLoginOverlay) currentLoginOverlay.style.display = "none";
                    window.location.href = "/chat";
                }, 100);
            } else {
                // Unauthorized domain
                if (currentLoginError) currentLoginError.style.display = "flex";
            }
        } catch (error) {
            console.error("Error decoding Google JWT:", error);
            const currentLoginError = document.getElementById("login-error");
            if (currentLoginError) {
                currentLoginError.style.display = "flex";
                const span = currentLoginError.querySelector("span");
                if (span) span.textContent = "Error authenticating. Please try again.";
            }
        }
    };

        // Logout handling
    const handleLogout = () => {
        localStorage.removeItem("dau_buddy_auth");
        localStorage.removeItem("dau_buddy_view");
        if (window.location.pathname === "/docs" || window.location.pathname.endsWith("docs.html")) {
            window.location.reload();
        } else {
            window.location.href = "/";
        }
    };
    if (logoutBtn) logoutBtn.addEventListener("click", handleLogout);
    if (landingLogoutBtn) landingLogoutBtn.addEventListener("click", handleLogout);
    const btnGetStarted = document.getElementById("hero-get-started-btn");
    const btnSignIn = document.getElementById("nav-signin-btn");
    const btnCloseLogin = document.getElementById("close-login-btn");
    const homeBtn = document.getElementById("home-btn");

    if (homeBtn) {
        if (homeBtn) homeBtn.addEventListener("click", () => {
            if (appContainer) appContainer.style.display = "none";
            const landingView = document.getElementById("landing-view");
            if (landingView) landingView.style.display = "block";
            localStorage.setItem("dau_buddy_view", "landing");
        });
    }



    if (btnGetStarted) btnGetStarted.addEventListener("click", window.openLoginModal);
    if (btnSignIn) btnSignIn.addEventListener("click", window.openLoginModal);
    if (btnCloseLogin) btnCloseLogin.addEventListener("click", window.closeLoginModal);


    // Tab Switching functionality
    const tabClaude = document.getElementById("tab-claude");
    const tabCursor = document.getElementById("tab-cursor");
    const tabOpenCode = document.getElementById("tab-opencode");

    const contentClaude = document.getElementById("content-claude");
    const contentCursor = document.getElementById("content-cursor");
    const contentOpenCode = document.getElementById("content-opencode");

    function resetTabs() {
        [tabClaude, tabCursor, tabOpenCode].forEach(tab => {
            if (tab) {
                tab.style.background = "transparent";
                tab.style.color = "#a0a0a0";
            }
        });
        [contentClaude, contentCursor, contentOpenCode].forEach(content => {
            if (content) content.style.display = "none";
        });
    }

    if (tabClaude) {
        if (tabClaude) tabClaude.addEventListener("click", () => {
            resetTabs();
            tabClaude.style.background = "#0f3b73";
            tabClaude.style.color = "white";
            contentClaude.style.display = "block";
        });
    }

    if (tabCursor) {
        if (tabCursor) tabCursor.addEventListener("click", () => {
            resetTabs();
            tabCursor.style.background = "#0f3b73";
            tabCursor.style.color = "white";
            contentCursor.style.display = "block";
        });
    }

    if (tabOpenCode) {
        if (tabOpenCode) tabOpenCode.addEventListener("click", () => {
            resetTabs();
            tabOpenCode.style.background = "#0f3b73";
            tabOpenCode.style.color = "white";
            contentOpenCode.style.display = "block";
        });
    }

    // Config Copy Buttons
    const copyClaudeBtn = document.getElementById("copy-claude-btn");
    if (copyClaudeBtn) {
        if (copyClaudeBtn) copyClaudeBtn.addEventListener("click", () => {
            navigator.clipboard.writeText(configCode.textContent).then(() => {
                copyClaudeBtn.textContent = "Copied!";
                copyClaudeBtn.style.background = "#10b981";
                copyClaudeBtn.style.borderColor = "#10b981";
                setTimeout(() => {
                    copyClaudeBtn.textContent = "Copy";
                    copyClaudeBtn.style.background = "rgba(255,255,255,0.1)";
                    copyClaudeBtn.style.borderColor = "#444";
                }, 2000);
            });
        });
    }

    const copyCursorBtn = document.getElementById("copy-cursor-btn");
    if (copyCursorBtn && cursorConfigCode) {
        if (copyCursorBtn) copyCursorBtn.addEventListener("click", () => {
            navigator.clipboard.writeText(cursorConfigCode.textContent).then(() => {
                copyCursorBtn.textContent = "Copied!";
                copyCursorBtn.style.background = "#10b981";
                copyCursorBtn.style.borderColor = "#10b981";
                setTimeout(() => {
                    copyCursorBtn.textContent = "Copy";
                    copyCursorBtn.style.background = "rgba(255,255,255,0.1)";
                    copyCursorBtn.style.borderColor = "#444";
                }, 2000);
            });
        });
    }

    const copyOpenCodeBtn = document.getElementById("copy-opencode-btn");
    const opencodeConfigCode = document.getElementById("opencode-config-code");
    if (copyOpenCodeBtn && opencodeConfigCode) {
        if (copyOpenCodeBtn) copyOpenCodeBtn.addEventListener("click", () => {
            navigator.clipboard.writeText(opencodeConfigCode.textContent).then(() => {
                copyOpenCodeBtn.textContent = "Copied!";
                copyOpenCodeBtn.style.background = "#10b981";
                copyOpenCodeBtn.style.borderColor = "#10b981";
                setTimeout(() => {
                    copyOpenCodeBtn.textContent = "Copy";
                    copyOpenCodeBtn.style.background = "rgba(255,255,255,0.1)";
                    copyOpenCodeBtn.style.borderColor = "#444";
                }, 2000);
            });
        });
    }

    const newKeyModal = document.getElementById("new-key-modal");
    const newKeyInput = document.getElementById("new-key-input");
    const copyNewKeyBtn = document.getElementById("copy-new-key-btn");
    const closeNewKeyModal = document.getElementById("close-new-key-modal");
    const doneNewKeyBtn = document.getElementById("done-new-key-btn");
    
    function closeKeyModal() {
        if (newKeyModal) {
            newKeyModal.style.display = "none";
            // Clear the input in the modal so it can't be inspected easily later
            if (newKeyInput) {
                newKeyInput.value = "";
            }
        }
    }

    if (closeNewKeyModal) closeNewKeyModal.addEventListener("click", closeKeyModal);
    if (doneNewKeyBtn) doneNewKeyBtn.addEventListener("click", closeKeyModal);
    
    if (copyNewKeyBtn && newKeyInput) {
        if (copyNewKeyBtn) copyNewKeyBtn.addEventListener("click", () => {
            if (newKeyInput.value) {
                navigator.clipboard.writeText(newKeyInput.value).then(() => {
                    copyNewKeyBtn.textContent = "Copied!";
                    copyNewKeyBtn.style.background = "#059669";
                    setTimeout(() => {
                        copyNewKeyBtn.textContent = "Copy";
                        copyNewKeyBtn.style.background = "#10b981";
                    }, 2000);
                });
            }
        });
    }

    // Profile Dropdown Toggle
    if (navProfileTrigger && profileDropdown) {
        if (navProfileTrigger) navProfileTrigger.addEventListener("click", (e) => {
            e.stopPropagation();
            if (profileDropdown.style.display === "flex") {
                profileDropdown.style.display = "none";
            } else {
                profileDropdown.style.display = "flex";
            }
        });
        
        // Close dropdown when clicking outside
        document.addEventListener("click", (e) => {
            if (!profileContainer.contains(e.target)) {
                profileDropdown.style.display = "none";
            }
        });

        const closeProfileBtn = document.getElementById("close-profile-btn");
        if (closeProfileBtn) {
            if (closeProfileBtn) closeProfileBtn.addEventListener("click", (e) => {
                e.stopPropagation();
                profileDropdown.style.display = "none";
            });
        }
    }

    // Landing Profile Dropdown Toggle
    if (landingProfileTrigger && landingProfileDropdown) {
        if (landingProfileTrigger) landingProfileTrigger.addEventListener("click", (e) => {
            e.stopPropagation();
            if (landingProfileDropdown.style.display === "flex") {
                landingProfileDropdown.style.display = "none";
            } else {
                landingProfileDropdown.style.display = "flex";
            }
        });
        
        // Close dropdown when clicking outside
        document.addEventListener("click", (e) => {
            if (landingProfileContainer && !landingProfileContainer.contains(e.target)) {
                landingProfileDropdown.style.display = "none";
            }
        });

        const landingCloseProfileBtn = document.getElementById("landing-close-profile-btn");
        if (landingCloseProfileBtn) {
            if (landingCloseProfileBtn) landingCloseProfileBtn.addEventListener("click", (e) => {
                e.stopPropagation();
                landingProfileDropdown.style.display = "none";
            });
        }
        
        
    }
});

