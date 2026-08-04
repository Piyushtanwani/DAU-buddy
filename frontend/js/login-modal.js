window.openLoginModal = function () {
    const storedSession = localStorage.getItem("dau_buddy_auth");
    if (storedSession) {
        try {
            const authData = JSON.parse(storedSession);
            if (authData.email && authData.credential) {
                // Already logged in, redirect based on current page
                const currentPath = window.location.pathname;
                if (currentPath.includes("api-key")) {
                    window.location.href = "/api-keys";
                } else {
                    window.location.href = "/chat";
                }
                return;
            }
        } catch (e) { }
    }
    const overlay = document.getElementById("login-overlay");
    if (overlay) {
        overlay.style.display = "flex";
        setTimeout(() => overlay.style.opacity = "1", 10);
    }
};

window.closeLoginModal = function () {
    const overlay = document.getElementById("login-overlay");
    if (overlay) {
        overlay.style.opacity = "0";
        setTimeout(() => overlay.style.display = "none", 300);
    }
};

document.addEventListener("DOMContentLoaded", () => {
    // Inject Google Auth Script if not present
    if (!document.querySelector('script[src="https://accounts.google.com/gsi/client"]')) {
        const script = document.createElement('script');
        script.src = "https://accounts.google.com/gsi/client";
        script.async = true;
        script.defer = true;
        document.head.appendChild(script);
    }

    if (!document.getElementById("login-overlay")) {
        const loginHtml = `
            <!-- ── Login Container Modal ─────────────────────────────────────── -->
            <div class="login-overlay" id="login-overlay" style="display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: #0f3b73; z-index: 1000; justify-content: center; align-items: center;">
                <div class="login-card" style="background: white; border-radius: 8px; padding: 30px; max-width: 400px; width: 100%; box-shadow: 0 4px 20px rgba(0,0,0,0.2); position: relative;">
                    <button class="close-modal-btn" id="close-login-btn" style="position: absolute; top: 15px; right: 15px; background: none; border: none; font-size: 20px; cursor: pointer; color: #666;"><i class="fa-solid fa-xmark"></i></button>
                    <div class="login-header" style="text-align: center; margin-bottom: 20px;">
                        <img src="/assets/dau_buddy_icon.png" alt="DAU Buddy" class="login-logo" style="width: 48px; height: 48px; margin-bottom: 10px; object-fit: contain;">
                        <h2 style="margin: 0; font-size: 24px; color: #111;">DAU Buddy</h2>
                        <p style="margin: 5px 0 0; font-size: 14px; color: #666;">Sign in with your university account to authenticate.</p>
                    </div>

                    <div class="login-error" id="login-error" style="display: none; background: #fee2e2; color: #b91c1c; padding: 10px; border-radius: 4px; margin-bottom: 15px; font-size: 13px; align-items: center; gap: 8px;">
                        <i class="fa-solid fa-circle-exclamation"></i>
                        <span>Access Restricted: Please use a valid @dau.ac.in email address.</span>
                    </div>

                    <div class="g_id_signin_container" style="display: flex; justify-content: center;">
                        <!-- Google Sign-In Button will be rendered here -->
                    </div>
                </div>
            </div>
        `;
        document.body.insertAdjacentHTML('beforeend', loginHtml);

        function initGoogleSignIn() {
            if (window.google && window.google.accounts && window.google.accounts.id) {
                google.accounts.id.initialize({
                    client_id: "590260573365-9151v4jkovetn7rhml7vhtfs5c0or2em.apps.googleusercontent.com",
                    callback: window.handleCredentialResponse || function (res) { if (window.processLogin) window.processLogin(res); },
                    context: "signin",
                    ux_mode: "popup",
                    auto_prompt: false
                });
                const btnContainer = document.querySelector('.g_id_signin_container');
                if (btnContainer) {
                    google.accounts.id.renderButton(btnContainer, {
                        type: "standard",
                        shape: "rectangular",
                        theme: "outline",
                        text: "signin_with",
                        size: "large",
                        logo_alignment: "left"
                    });
                }
            } else {
                setTimeout(initGoogleSignIn, 100);
            }
        }
        initGoogleSignIn();
    }

    // Attach click events
    const closeBtn = document.getElementById("close-login-btn");
    if (closeBtn) closeBtn.addEventListener("click", window.closeLoginModal);

    // For overlay click closing
    const overlay = document.getElementById("login-overlay");
    if (overlay) overlay.addEventListener("click", (e) => {
        if (e.target === overlay) window.closeLoginModal();
    });

    // Replace the href redirects with modal open for docs.html
    const docsLoginBtn = document.getElementById("docs-login-btn");
    if (docsLoginBtn) {
        if (docsLoginBtn.textContent.trim().includes("Sign")) {
            docsLoginBtn.removeAttribute("onclick");
            docsLoginBtn.addEventListener("click", (e) => {
                e.preventDefault();
                window.openLoginModal();
            });
        }
    }

    // Override global processLogin behavior if defined, so it reloads page correctly
    const originalProcessLogin = window.processLogin;
    window.processLogin = (response) => {
        if (originalProcessLogin) {
            originalProcessLogin(response);
        } else {
            // Fallback for pages without app.js
            try {
                const payloadBase64 = response.credential.split('.')[1];
                const decodedPayload = JSON.parse(atob(payloadBase64.replace(/-/g, '+').replace(/_/g, '/')));
                if (decodedPayload.email) {
                    localStorage.setItem("dau_buddy_auth", JSON.stringify({
                        email: decodedPayload.email,
                        name: decodedPayload.name,
                        picture: decodedPayload.picture,
                        credential: response.credential
                    }));

                    const currentLoginOverlay = document.getElementById("login-overlay");
                    if (currentLoginOverlay) currentLoginOverlay.style.opacity = "0";
                    setTimeout(() => {
                        if (currentLoginOverlay) currentLoginOverlay.style.display = "none";
                        // Redirect based on which page the user is currently on
                        const currentPath = window.location.pathname;
                        if (currentPath.includes("api-key")) {
                            window.location.href = "/api-keys";
                        } else {
                            window.location.href = "/chat";
                        }
                    }, 400);
                } else {
                    const loginError = document.getElementById("login-error");
                    if (loginError) loginError.style.display = "flex";
                }
            } catch (error) {
                console.error("Error decoding Google JWT in fallback:", error);
                const loginError = document.getElementById("login-error");
                if (loginError) {
                    loginError.style.display = "flex";
                    const span = loginError.querySelector("span");
                    if (span) span.textContent = "Error authenticating. Please try again.";
                }
            }
        }
    };
});
