/* ==============================================================================
   DA-IICT DAU Buddy - Profile Logic (profile.js)
   ============================================================================== */

document.addEventListener("DOMContentLoaded", () => {
    // Require authentication to view profile page
    const authDataRaw = localStorage.getItem("dau_buddy_auth");
    if (!authDataRaw) {
        window.location.href = '/?view=login';
        return;
    }

    let authData;
    try {
        authData = JSON.parse(authDataRaw);
    } catch (e) {
        window.location.href = '/?view=login';
        return;
    }

    if (!authData.credential) {
        window.location.href = '/?view=login';
        return;
    }

    // Populate Profile Header
    const avatarImg = document.getElementById("main-profile-avatar");
    const nameEl = document.getElementById("main-profile-name");
    const emailEl = document.getElementById("main-profile-email");
    const roleEl = document.getElementById("main-profile-role");
    
    if (avatarImg && authData.picture) {
        avatarImg.src = authData.picture;
    }
    
    if (nameEl && authData.name) {
        nameEl.textContent = authData.name;
    }
    
    if (emailEl && authData.email) {
        emailEl.textContent = authData.email;
    }
    
    if (roleEl) {
        roleEl.textContent = authData.role || "Student";
    }

    // Populate Academic Grid
    const academicGrid = document.getElementById("academic-grid");
    const academicInfoCard = document.getElementById("academic-info-card");
    if (academicGrid && academicInfoCard) {
        // Here we extract basic information from the email if available.
        // DA-IICT emails for students look like: <id>@daiict.ac.in
        const email = authData.email || "";
        const idMatch = email.match(/^(\d{9})@/);
        
        if (idMatch || authData.role) {
            academicInfoCard.style.display = "block";
            let html = "";
            
            if (idMatch) {
                const studentId = idMatch[1];
                html += `
                    <div class="academic-item">
                        <span class="academic-label">Student ID</span>
                        <span class="academic-value">${studentId}</span>
                    </div>
                    <div class="academic-item" id="academic-program-container" style="display: none;">
                        <span class="academic-label">Program</span>
                        <span class="academic-value" id="academic-program-val">...</span>
                    </div>
                    <div class="academic-item" id="academic-semester-container" style="display: none;">
                        <span class="academic-label">Semester</span>
                        <span class="academic-value" id="academic-semester-val">...</span>
                    </div>
                `;
                
                // Try to infer batch year (first 4 digits)
                const batchYear = studentId.substring(0, 4);
                html += `
                    <div class="academic-item">
                        <span class="academic-label">Batch</span>
                        <span class="academic-value">${batchYear}</span>
                    </div>
                `;
            }
            
            html += `
                <div class="academic-item">
                    <span class="academic-label">Account Type</span>
                    <span class="academic-value">${authData.role || "Student"}</span>
                </div>
            `;
            
            academicGrid.innerHTML = html;
        }
    }

    // Load Recent Conversations from localStorage
    const recentChatsList = document.getElementById("recent-chats-list");
    if (recentChatsList) {
        let userKey = "guest";
        if (authData.email) {
            userKey = authData.email.split('@')[0];
        }
        const storageKey = "dau_buddy_chats_" + userKey;
        
        try {
            const storedChats = localStorage.getItem(storageKey);
            if (storedChats) {
                const chatSessions = JSON.parse(storedChats);
                
                if (chatSessions && chatSessions.length > 0) {
                    recentChatsList.innerHTML = "";
                    
                    // Show up to 5 recent chats
                    const recentSessions = chatSessions.slice(0, 5);
                    
                    recentSessions.forEach(session => {
                        // Generate a date string
                        const date = new Date(session.timestamp);
                        const timeStr = date.toLocaleDateString(undefined, { 
                            month: 'short', 
                            day: 'numeric',
                            hour: '2-digit', 
                            minute: '2-digit'
                        });
                        
                        const title = session.title || "New Chat";
                        
                        // Pick icon based on first question loosely
                        let iconClass = "fa-regular fa-message";
                        const lowerTitle = title.toLowerCase();
                        if (lowerTitle.includes("book") || lowerTitle.includes("library")) iconClass = "fa-solid fa-book";
                        else if (lowerTitle.includes("timetable") || lowerTitle.includes("holiday")) iconClass = "fa-solid fa-calendar-days";
                        else if (lowerTitle.includes("prof") || lowerTitle.includes("faculty")) iconClass = "fa-solid fa-user-tie";
                        
                        const chatHtml = `
                            <a href="/chat?session=${session.id}" class="recent-chat-item">
                                <div class="recent-chat-icon">
                                    <i class="${iconClass}"></i>
                                </div>
                                <div class="recent-chat-info">
                                    <span class="recent-chat-title">${title}</span>
                                    <span class="recent-chat-time">${timeStr}</span>
                                </div>
                            </a>
                        `;
                        
                        recentChatsList.insertAdjacentHTML('beforeend', chatHtml);
                    });
                } else {
                    recentChatsList.innerHTML = `
                        <div class="timetable-empty-state">
                            <i class="fa-regular fa-comments"></i>
                            <p>No recent conversations.</p>
                            <button class="chat-fallback-btn" onclick="window.location.href='/chat'" style="margin-top: 8px;">Start a Chat</button>
                        </div>
                    `;
                }
            } else {
                recentChatsList.innerHTML = `
                    <div class="timetable-empty-state">
                        <i class="fa-regular fa-comments"></i>
                        <p>No recent conversations.</p>
                        <button class="chat-fallback-btn" onclick="window.location.href='/chat'" style="margin-top: 8px;">Start a Chat</button>
                    </div>
                `;
            }
        } catch (e) {
            console.error("Error loading chat history:", e);
            recentChatsList.innerHTML = `<div class="loading-state">Could not load recent chats.</div>`;
        }
    }
    
    // Load Timetable
    loadWeeklyTimetable(authData);
});

async function loadWeeklyTimetable(authData) {
    const timetableCard = document.getElementById("timetable-card");
    const metaInfo = document.getElementById("timetable-meta-info");
    if (!timetableCard) return;

    try {
        const response = await fetch('/api/me/timetable', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ credential: authData.credential })
        });

        if (!response.ok) {
            throw new Error('Failed to fetch timetable');
        }

        const data = await response.json();
        
        if (data.program && metaInfo) {
            let metaText = data.program;
            if (data.semester) metaText += ` (Sem ${data.semester})`;
            metaInfo.textContent = metaText;

            // Update academic grid if program/semester available
            const progContainer = document.getElementById("academic-program-container");
            const progVal = document.getElementById("academic-program-val");
            if (progContainer && progVal) {
                progVal.textContent = data.program;
                progContainer.style.display = 'flex'; // Or block, depending on CSS
            }

            const semContainer = document.getElementById("academic-semester-container");
            const semVal = document.getElementById("academic-semester-val");
            if (data.semester && semContainer && semVal) {
                semVal.textContent = data.semester;
                semContainer.style.display = 'flex';
            }
        }

        const schedule = data.schedule || [];
        
        if (schedule.length === 0) {
            timetableCard.innerHTML = `
                <div id="timetable-content" class="timetable-empty-state" style="padding: 24px;">
                    <i class="fa-regular fa-calendar-xmark"></i>
                    <p>No timetable found for your account.</p>
                    <button class="chat-fallback-btn" onclick="window.location.href='/chat?prompt=Show%20full%20timetable'" style="margin-top: 8px;">Ask DAU Buddy</button>
                </div>
            `;
            return;
        }

        // Group by day
        const days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
        const grouped = {};
        days.forEach(d => grouped[d] = []);
        
        schedule.forEach(slot => {
            const day = slot.day_of_week;
            if (grouped[day]) {
                grouped[day].push(slot);
            }
        });

        // Determine current day for default active tab
        const currentDayIndex = new Date().getDay(); // 0 is Sunday, 1 is Monday
        const activeDay = currentDayIndex === 0 ? 'Monday' : days[currentDayIndex - 1];

        // Build HTML
        let html = '<div class="timetable-days-nav">';
        days.forEach(day => {
            if (grouped[day].length > 0 || day === activeDay || day !== 'Saturday') {
                const isActive = day === activeDay ? 'active' : '';
                html += `<button class="timetable-day-tab ${isActive}" data-day="${day}">${day.substring(0, 3)}</button>`;
            }
        });
        html += '</div>';

        html += '<div class="timetable-slots-container">';
        days.forEach(day => {
            const isActive = day === activeDay ? 'style="display: block;"' : 'style="display: none;"';
            html += `<div class="timetable-day-content" id="day-content-${day}" ${isActive}>`;
            
            if (grouped[day].length === 0) {
                html += `
                    <div class="timetable-empty-state" style="margin-top: 24px;">
                        <i class="fa-regular fa-face-smile"></i>
                        <p>No classes scheduled for ${day}.</p>
                    </div>
                `;
            } else {
                grouped[day].forEach(slot => {
                    const startStr = slot.start_time.substring(0, 5);
                    const endStr = slot.end_time.substring(0, 5);
                    
                    html += `
                        <div class="timetable-slot">
                            <div class="slot-time">
                                <div>${startStr}</div>
                                <div style="font-size:12px; color:var(--text-muted); font-weight:400;">to ${endStr}</div>
                            </div>
                            <div class="slot-details">
                                <div class="slot-course">${slot.course_code || ''} ${slot.course_name ? '- ' + slot.course_name : ''}</div>
                                <div class="slot-meta">
                                    ${slot.room ? `<span><i class="fa-solid fa-location-dot"></i> ${slot.room}</span>` : ''}
                                    ${slot.faculty_name ? `<span><i class="fa-solid fa-user-tie"></i> ${slot.faculty_name}</span>` : ''}
                                    ${slot.session_type ? `<span style="background:#e2e8f0; padding:2px 8px; border-radius:12px; font-weight:500;">${slot.session_type}</span>` : ''}
                                </div>
                            </div>
                        </div>
                    `;
                });
            }
            html += `</div>`;
        });
        html += '</div>';

        timetableCard.innerHTML = html;

        // Add event listeners for tabs
        const tabs = timetableCard.querySelectorAll('.timetable-day-tab');
        tabs.forEach(tab => {
            tab.addEventListener('click', (e) => {
                // Remove active class from all tabs
                tabs.forEach(t => t.classList.remove('active'));
                // Hide all content
                timetableCard.querySelectorAll('.timetable-day-content').forEach(c => c.style.display = 'none');
                
                // Add active to clicked
                const clickedTab = e.currentTarget;
                clickedTab.classList.add('active');
                
                // Show content
                const day = clickedTab.getAttribute('data-day');
                document.getElementById(`day-content-${day}`).style.display = 'block';
            });
        });

    } catch (e) {
        console.error("Timetable error:", e);
        timetableCard.innerHTML = `
            <div id="timetable-content" class="timetable-empty-state" style="padding: 24px;">
                <i class="fa-solid fa-triangle-exclamation" style="color: #ef4444;"></i>
                <p>Failed to load timetable.</p>
                <button class="chat-fallback-btn" onclick="loadWeeklyTimetable(JSON.parse(localStorage.getItem('dau_buddy_auth')))" style="margin-top: 8px;">Retry</button>
            </div>
        `;
    }
}
