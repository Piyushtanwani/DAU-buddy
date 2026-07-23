document.addEventListener('DOMContentLoaded', () => {
    const tabBtns = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');

    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            // Remove active class from all buttons and contents
            tabBtns.forEach(b => b.classList.remove('active'));
            tabContents.forEach(c => c.classList.remove('active'));

            // Add active class to clicked button
            btn.classList.add('active');

            // Add active class to corresponding content
            const targetId = btn.getAttribute('data-target');
            document.getElementById(targetId).classList.add('active');
        });
    });

    // Profile Dropdown Logic
    const navProfileTrigger = document.getElementById("nav-profile-trigger");
    const profileDropdown = document.getElementById("profile-dropdown");
    const profileContainer = document.getElementById("profile-container");
    const closeProfileBtn = document.getElementById("close-profile-btn");
    const logoutBtn = document.getElementById("logout-btn");

    if (navProfileTrigger && profileDropdown) {
        navProfileTrigger.addEventListener("click", (e) => {
            e.stopPropagation();
            if (profileDropdown.style.display === "flex") {
                profileDropdown.style.display = "none";
            } else {
                profileDropdown.style.display = "flex";
            }
        });

        document.addEventListener("click", (e) => {
            if (profileContainer && !profileContainer.contains(e.target)) {
                profileDropdown.style.display = "none";
            }
        });

        if (closeProfileBtn) {
            closeProfileBtn.addEventListener("click", (e) => {
                e.stopPropagation();
                profileDropdown.style.display = "none";
            });
        }
    }

    if (logoutBtn) {
        logoutBtn.addEventListener("click", () => {
            localStorage.removeItem("dau_buddy_auth");
            window.location.reload();
        });
    }

    // Populate user profile info from localStorage
    const authDataStr = localStorage.getItem("dau_buddy_auth");
    if (authDataStr) {
        try {
            const authData = JSON.parse(authDataStr);
            if (authData.picture) {
                if (navProfileTrigger) navProfileTrigger.src = authData.picture;
                const dropdownAvatar = document.getElementById("dropdown-avatar");
                if (dropdownAvatar) dropdownAvatar.src = authData.picture;
            }
            if (authData.name) {
                const dropdownName = document.getElementById("dropdown-name");
                if (dropdownName) dropdownName.textContent = authData.name;
            }
            if (authData.email) {
                const dropdownEmail = document.getElementById("dropdown-email");
                if (dropdownEmail) dropdownEmail.textContent = authData.email;
            }
            if (authData.role) {
                const dropdownRole = document.getElementById("dropdown-role");
                if (dropdownRole) dropdownRole.textContent = authData.role;
                
                const dashboardBtn = document.getElementById("nav-dashboard-btn");
                if (dashboardBtn) {
                    if (authData.role.includes("Maintainer")) {
                        dashboardBtn.style.display = "flex";
                    } else {
                        dashboardBtn.style.display = "none";
                    }
                }
            }
        } catch (e) {
            console.error("Error parsing auth data:", e);
            if (profileContainer) profileContainer.style.display = "none";
        }
    } else {
        if (profileContainer) profileContainer.style.display = "none";
        const navDashboardLinkBtn = document.getElementById("nav-dashboard-link-btn");
        if (navDashboardLinkBtn) navDashboardLinkBtn.style.display = "none";
        
        // Add a sign in button dynamically if we want, or just hide the profile
        const navLinks = document.querySelector('.nav-links');
        if (navLinks) {
            const signInBtn = document.createElement("button");
            signInBtn.className = "nav-signout-btn";
            signInBtn.textContent = "Sign In";
            signInBtn.onclick = () => window.location.href = "/?view=login";
            navLinks.appendChild(signInBtn);
        }
    }
});
