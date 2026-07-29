document.addEventListener("DOMContentLoaded", async () => {
    const errorAlert = document.getElementById("error-alert");
    const errorText = document.getElementById("error-text");
    const spinner = document.getElementById("loading-spinner");
    const content = document.getElementById("dashboard-content");

    const totalUsers = document.getElementById("total-users");
    const newUsers = document.getElementById("new-users");
    const totalQueries = document.getElementById("total-queries");
    const activeUsers = document.getElementById("active-users");
    const chatUsers = document.getElementById("chat-users");
    
    const queriesUserTableBody = document.querySelector("#queries-user-table tbody");

    let queriesPerUserData = [];
    let currentSort = { column: 'count', direction: 'desc' };

    function showError(msg) {
        spinner.style.display = "none";
        content.style.display = "none";
        errorAlert.style.display = "block";
        errorText.textContent = msg;
    }

    const storedSession = localStorage.getItem("dau_buddy_auth");
    if (!storedSession) {
        showError("You must be logged in to access this page.");
        return;
    }

    let authData;
    try {
        authData = JSON.parse(storedSession);
    } catch(e) {
        showError("Invalid session. Please login again.");
        return;
    }

    if (!authData.role || !authData.role.includes("Maintainer")) {
        showError("Access Denied: Maintainer role is required to view this dashboard.");
        return;
    }

    if (!authData.credential) {
        showError("Missing authentication credentials. Please login again.");
        return;
    }

    try {
        const response = await fetch("/api/maintainer/dashboard", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ credential: authData.credential })
        });

        if (!response.ok) {
            const err = await response.json();
            showError(err.detail || "Failed to load dashboard data.");
            return;
        }

        const data = await response.json();

        // Populate metrics
        totalUsers.textContent = data.users.total;
        newUsers.textContent = data.users.new_last_7_days;
        totalQueries.textContent = data.platform.total_queries;
        activeUsers.textContent = data.platform.active_users;
        if (chatUsers && data.platform.chat_users !== undefined) {
            chatUsers.textContent = data.platform.chat_users;
        }

        // Initialize Charts
        initCharts(data);

        // Populate Sortable Table
        queriesPerUserData = data.queries_per_user || [];
        renderQueriesTable();

        // Setup Sorting listeners
        document.querySelectorAll("#queries-user-table th").forEach(th => {
            th.addEventListener('click', () => {
                const column = th.dataset.sort;
                if (currentSort.column === column) {
                    currentSort.direction = currentSort.direction === 'asc' ? 'desc' : 'asc';
                } else {
                    currentSort.column = column;
                    currentSort.direction = 'desc';
                }
                
                // Update icons
                document.querySelectorAll("#queries-user-table th i").forEach(i => {
                    i.className = 'fa-solid fa-sort';
                });
                th.querySelector('i').className = currentSort.direction === 'asc' ? 'fa-solid fa-sort-up' : 'fa-solid fa-sort-down';

                renderQueriesTable();
            });
        });

        spinner.style.display = "none";
        content.style.display = "block";
        
        // Initialize Feedback Monitoring
        initFeedback(authData);
        
        // Setup Profile Dropdown
        const navProfileTrigger = document.getElementById("nav-profile-trigger");
        const profileDropdown = document.getElementById("profile-dropdown");
        const closeProfileBtn = document.getElementById("close-profile-btn");
        const logoutBtn = document.getElementById("logout-btn");

        if (navProfileTrigger && profileDropdown) {
            navProfileTrigger.addEventListener("click", function(e) {
                e.stopPropagation();
                profileDropdown.style.display = (profileDropdown.style.display === "flex") ? "none" : "flex";
            });
            
            if (closeProfileBtn) {
                closeProfileBtn.addEventListener("click", function() {
                    profileDropdown.style.display = "none";
                });
            }
            
            document.addEventListener("click", function(e) {
                if (!navProfileTrigger.contains(e.target) && !profileDropdown.contains(e.target)) {
                    profileDropdown.style.display = "none";
                }
            });
        }

        if (logoutBtn) {
            logoutBtn.addEventListener("click", function() {
                localStorage.removeItem("dau_buddy_auth");
                window.location.href = "/";
            });
        }

        // Populate profile info
        if (authData) {
            const dropdownName = document.getElementById("dropdown-name");
            const dropdownEmail = document.getElementById("dropdown-email");
            const dropdownRole = document.getElementById("dropdown-role");
            const dropdownAvatar = document.getElementById("dropdown-avatar");
            
            if (dropdownName) dropdownName.textContent = authData.name || "Welcome!";
            if (dropdownEmail) dropdownEmail.textContent = authData.email || "Authenticated User";
            if (dropdownRole) dropdownRole.textContent = authData.role || "Maintainer";
            
            if (authData.credential) {
                try {
                    const parts = authData.credential.split('.');
                    if (parts.length === 3) {
                        const payload = JSON.parse(atob(parts[1]));
                        if (payload.picture) {
                            if (navProfileTrigger) navProfileTrigger.src = payload.picture;
                            if (dropdownAvatar) dropdownAvatar.src = payload.picture;
                        }
                    }
                } catch(e) {}
            }
        }

    } catch (e) {
        console.error("Dashboard fetch error", e);
        showError("Network error while fetching dashboard data.");
    }

    function renderQueriesTable() {
        queriesUserTableBody.innerHTML = "";
        
        if (queriesPerUserData.length === 0) {
            queriesUserTableBody.innerHTML = "<tr><td colspan='2' style='text-align:center;'>No data available</td></tr>";
            return;
        }

        const sortedData = [...queriesPerUserData].sort((a, b) => {
            let valA = a[currentSort.column];
            let valB = b[currentSort.column];
            
            if (typeof valA === 'string') valA = valA.toLowerCase();
            if (typeof valB === 'string') valB = valB.toLowerCase();

            if (valA < valB) return currentSort.direction === 'asc' ? -1 : 1;
            if (valA > valB) return currentSort.direction === 'asc' ? 1 : -1;
            return 0;
        });

        sortedData.forEach(user => {
            const tr = document.createElement("tr");
            const emailTd = document.createElement("td");
            emailTd.textContent = user.email;
            const countTd = document.createElement("td");
            countTd.textContent = user.count;
            tr.appendChild(emailTd);
            tr.appendChild(countTd);
            queriesUserTableBody.appendChild(tr);
        });
    }

    function initCharts(data) {
        Chart.defaults.font.family = "'Open Sans', sans-serif";
        Chart.defaults.color = '#555';

        // 1. Signups Line Chart
        const signupsCtx = document.getElementById('signups-chart');
        if (signupsCtx && data.signups_over_time) {
            new Chart(signupsCtx, {
                type: 'line',
                data: {
                    labels: data.signups_over_time.map(d => d.date),
                    datasets: [{
                        label: 'New Signups',
                        data: data.signups_over_time.map(d => d.count),
                        borderColor: '#0f3b73',
                        backgroundColor: 'rgba(15, 59, 115, 0.1)',
                        fill: true,
                        tension: 0.3,
                        pointBackgroundColor: '#0f3b73'
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        y: { beginAtZero: true, ticks: { stepSize: 1 } }
                    }
                }
            });
        }

        // 2. Tool Usage Horizontal Bar Chart
        const toolsCtx = document.getElementById('tools-chart');
        if (toolsCtx && data.tools) {
            new Chart(toolsCtx, {
                type: 'bar',
                data: {
                    labels: data.tools.map(t => t.tool_name),
                    datasets: [{
                        label: 'Invocations',
                        data: data.tools.map(t => t.count),
                        backgroundColor: '#3b82f6',
                        borderRadius: 4
                    }]
                },
                options: {
                    indexAxis: 'y',
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        x: { beginAtZero: true, ticks: { stepSize: 1 } }
                    }
                }
            });
        }

        // 3. Client Usage Pie Chart
        const clientsCtx = document.getElementById('clients-chart');
        if (clientsCtx && data.clients) {
            const colors = ['#0f3b73', '#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6'];
            new Chart(clientsCtx, {
                type: 'doughnut',
                data: {
                    labels: data.clients.map(c => c.client_name),
                    datasets: [{
                        data: data.clients.map(c => c.count),
                        backgroundColor: colors.slice(0, data.clients.length),
                        borderWidth: 1
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { position: 'right' }
                    },
                    cutout: '60%'
                }
            });
        }
        // 4. Roles Bar Chart
        const rolesCtx = document.getElementById('roles-chart');
        if (rolesCtx && data.roles) {
            new Chart(rolesCtx, {
                type: 'bar',
                data: {
                    labels: data.roles.map(r => r.role),
                    datasets: [{
                        label: 'Signed Up',
                        data: data.roles.map(r => r.count),
                        backgroundColor: '#10b981',
                        borderRadius: 4
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        y: { beginAtZero: true, ticks: { stepSize: 1 } }
                    }
                }
            });
        }
    }
    
    // --- Feedback Monitoring Logic ---
    async function initFeedback(authData) {
        const feedbackContainer = document.getElementById("feedback-monitoring");
        const loading = document.getElementById("feedback-loading");
        const errorDiv = document.getElementById("feedback-error");
        const pendingGrid = document.getElementById("pending-feedbacks");
        const resolvedGrid = document.getElementById("resolved-feedbacks");
        
        feedbackContainer.style.display = "block";
        loading.style.display = "block";
        errorDiv.style.display = "none";
        pendingGrid.innerHTML = "";
        resolvedGrid.innerHTML = "";
        
        try {
            const response = await fetch(`/api/admin/feedbacks`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ credential: authData.credential })
            });
            
            if (!response.ok) {
                throw new Error("Failed to load feedbacks");
            }
            
            const feedbacks = await response.json();
            loading.style.display = "none";
            
            const pending = feedbacks.filter(f => f.status !== 'Resolved');
            const resolved = feedbacks.filter(f => f.status === 'Resolved');
            
            // Update Counts
            document.getElementById("total-feedback-count").textContent = `(Total: ${feedbacks.length})`;
            document.getElementById("pending-count").textContent = pending.length;
            document.getElementById("resolved-count").textContent = resolved.length;
            
            renderFeedbacks(pending, pendingGrid, true, authData);
            renderFeedbacks(resolved, resolvedGrid, false, authData);
            
            if (pending.length === 0) {
                pendingGrid.innerHTML = "<p style='color:#666; padding: 20px;'>No pending feedback.</p>";
            }
            if (resolved.length === 0) {
                resolvedGrid.innerHTML = "<p style='color:#666; padding: 20px;'>No resolved feedback.</p>";
            }
            
        } catch (e) {
            console.error(e);
            loading.style.display = "none";
            errorDiv.style.display = "block";
            errorDiv.textContent = "Error loading feedback: " + e.message;
        }
    }
    
    function renderFeedbacks(feedbacks, container, isPending, authData) {
        feedbacks.forEach(f => {
            const card = document.createElement("div");
            card.className = "feedback-card";
            card.id = `feedback-${f.id}`;
            
            let badgeBg = "#dcfce7", badgeColor = "#166534";
            const catLower = f.category.toLowerCase();
            if (catLower.includes("bug")) { badgeBg = "#fee2e2"; badgeColor = "#991b1b"; }
            else if (catLower.includes("feature")) { badgeBg = "#dbeafe"; badgeColor = "#1e40af"; }
            else if (catLower.includes("improvement")) { badgeBg = "#ffedd5"; badgeColor = "#9a3412"; }
            
            const dateStr = new Date(f.created_at).toLocaleString();
            
            let resolveHtml = "";
            if (isPending) {
                resolveHtml = `
                <div class="feedback-actions">
                    <button class="btn-resolve" onclick="resolveFeedback(${f.id}, '${authData.credential}')">
                        <i class="fa-solid fa-check"></i> Resolve & Email
                    </button>
                </div>`;
            }
            
            card.innerHTML = `
                <div class="feedback-card-header">
                    <span class="feedback-category" style="background:${badgeBg}; color:${badgeColor}">${f.category}</span>
                    <span class="feedback-date">${dateStr}</span>
                </div>
                <h4 class="feedback-subject">${f.subject}</h4>
                <div class="feedback-meta">
                    <div><i class="fa-solid fa-envelope"></i> ${f.user_email}</div>
                    <div><i class="fa-solid fa-user-tag"></i> ${f.role}</div>
                </div>
                <div class="feedback-desc">${f.description}</div>
                ${resolveHtml}
            `;
            
            container.appendChild(card);
        });
    }
    
    window.switchFeedbackTab = function(tabName) {
        document.querySelectorAll('.feedback-tab').forEach(t => t.classList.remove('active'));
        document.querySelector(`.feedback-tab[data-tab="${tabName}"]`).classList.add('active');
        
        if (tabName === 'pending') {
            document.getElementById('pending-feedbacks').style.display = 'grid';
            document.getElementById('resolved-feedbacks').style.display = 'none';
        } else {
            document.getElementById('pending-feedbacks').style.display = 'none';
            document.getElementById('resolved-feedbacks').style.display = 'grid';
        }
    };
    
    window.resolveFeedback = async function(id, credentialToken) {
        const btn = document.querySelector(`#feedback-${id} .btn-resolve`);
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Resolving...';
        }
        
        try {
            const response = await fetch(`/api/admin/feedbacks/${id}/resolve`, {
                method: 'POST',
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ credential: credentialToken })
            });
            
            if (!response.ok) throw new Error("Failed to resolve feedback");
            
            // Reload feedback to update lists
            // Retrieve authData from localStorage to re-init
            const storedSession = localStorage.getItem("dau_buddy_auth");
            if (storedSession) {
                initFeedback(JSON.parse(storedSession));
            }
            
        } catch (e) {
            console.error(e);
            alert("Error resolving feedback: " + e.message);
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '<i class="fa-solid fa-check"></i> Resolve & Email';
            }
        }
    };
});
