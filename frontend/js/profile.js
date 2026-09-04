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
    loadElectives(authData);
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
                            <div class="slot-details" style="flex-grow: 1;">
                                <div class="slot-course">${slot.course_code || ''} ${slot.course_name ? '- ' + slot.course_name : ''}</div>
                                <div class="slot-meta">
                                    ${slot.room ? `<span><i class="fa-solid fa-location-dot"></i> ${slot.room}</span>` : ''}
                                    ${slot.faculty_name ? `<span><i class="fa-solid fa-user-tie"></i> ${slot.faculty_name}</span>` : ''}
                                    ${slot.session_type ? `<span style="background:#e2e8f0; padding:2px 8px; border-radius:12px; font-weight:500;">${slot.session_type}</span>` : ''}
                                </div>
                            </div>
                            <div class="slot-actions" style="display: flex; gap: 4px; flex-direction: column;">
                                ${slot.is_personal_modification ? `
                                    <button title="Revert to Official" onclick="deleteModification(${slot.modification_id || 'null'}, ${slot.id})" style="background:none; border:none; color:#ef4444; cursor:pointer;"><i class="fa-solid fa-rotate-left"></i></button>
                                ` : `
                                    <button title="Edit Slot" onclick="openEditModal(${slot.id}, '${slot.course_code || ''}', '${slot.room || ''}', '${day}', '${slot.start_time}', '${slot.end_time}')" style="background:none; border:none; color:#64748b; cursor:pointer;"><i class="fa-solid fa-pen"></i></button>
                                    <button title="Cancel/Remove Slot" onclick="addModification('delete', ${slot.id})" style="background:none; border:none; color:#ef4444; cursor:pointer;"><i class="fa-solid fa-trash"></i></button>
                                `}
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


/* ==============================================================================
   Electives Management
   ============================================================================== */
async function loadElectives(authData) {
    if (!authData.role.startsWith('Student')) return;
    document.getElementById('electives-section').style.display = 'block';
    
    try {
        const response = await fetch('/api/me/electives', {
            method: 'GET',
            headers: {
                'Authorization': `Bearer ${authData.credential}`
            }
        });
        if (!response.ok) throw new Error('Failed to fetch electives');
        const data = await response.json();
        renderElectives(data.selected_electives || []);
        populateElectiveDropdown(data.available_electives || []);
    } catch (e) {
        console.error(e);
        document.getElementById('electives-container').innerHTML = '<div style="color: #ef4444; font-size: 14px;">Failed to load electives.</div>';
    }
}


function populateElectiveDropdown(availableElectives) {
    const select = document.getElementById('new-elective-input');
    if (!select || select.tagName !== 'SELECT') return; // Defensive check
    select.innerHTML = '<option value="">Select an elective...</option>';
    
    // Sort by course code
    availableElectives.sort((a, b) => (a.course_code || '').localeCompare(b.course_code || ''));
    
    availableElectives.forEach(e => {
        if (!e.course_code) return;
        const option = document.createElement('option');
        option.value = e.course_code;
        option.textContent = `${e.course_code} - ${e.course_name || 'Elective'}`;
        select.appendChild(option);
    });
}

function renderElectives(electives) {
    const container = document.getElementById('electives-container');
    if (electives.length === 0) {
        container.innerHTML = '<div style="font-size: 14px; color: #64748b; padding: 12px; background: #f8fafc; border-radius: 6px; border: 1px dashed #cbd5e1;">No electives selected.</div>';
        return;
    }
    
    let html = '<div style="display: flex; flex-wrap: wrap; gap: 8px;">';
    electives.forEach(code => {
        html += `
            <div style="background: #e0f2fe; color: #0284c7; padding: 4px 12px; border-radius: 16px; font-size: 13px; font-weight: 600; display: flex; align-items: center; gap: 6px; border: 1px solid #bae6fd;">
                ${code}
                <i class="fa-solid fa-xmark" style="cursor: pointer; opacity: 0.7;" onclick="removeElective('${code}')" title="Remove"></i>
            </div>
        `;
    });
    html += '</div>';
    container.innerHTML = html;
}

async function addElective() {
    const input = document.getElementById('new-elective-input');
    const courseCode = input.value;
    if (!courseCode) return;
    
    const authDataRaw = localStorage.getItem("dau_buddy_auth");
    if (!authDataRaw) return;
    const authData = JSON.parse(authDataRaw);
    
    try {
        const response = await fetch('/api/me/electives', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authData.credential}`
            },
            body: JSON.stringify({ action: 'add', course_code: courseCode })
        });
        if (!response.ok) {
            const err = await response.json();
            alert(err.detail || 'Failed to add elective');
            return;
        }
        input.value = '';
        await loadElectives(authData);
        await loadWeeklyTimetable(authData);
    } catch (e) {
        console.error(e);
        alert('Failed to add elective.');
    }
}

async function removeElective(courseCode) {
    if (!confirm(`Are you sure you want to remove ${courseCode}?`)) return;
    
    const authDataRaw = localStorage.getItem("dau_buddy_auth");
    if (!authDataRaw) return;
    const authData = JSON.parse(authDataRaw);
    
    try {
        const response = await fetch('/api/me/electives', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authData.credential}`
            },
            body: JSON.stringify({ action: 'remove', course_code: courseCode })
        });
        if (!response.ok) throw new Error('Failed to remove elective');
        await loadElectives(authData);
        await loadWeeklyTimetable(authData);
    } catch (e) {
        console.error(e);
        alert('Failed to remove elective.');
    }
}

/* ==============================================================================
   Timetable Modifications
   ============================================================================== */
function openEditModal(timetableId, courseCode, room, day, startTime, endTime) {
    document.getElementById('edit-timetable-id').value = timetableId;
    document.getElementById('edit-course').value = courseCode || '';
    document.getElementById('edit-room').value = room || '';
    document.getElementById('edit-day').value = day || 'Monday';
    
    if(startTime) document.getElementById('edit-start').value = startTime.substring(0, 5);
    if(endTime) document.getElementById('edit-end').value = endTime.substring(0, 5);
    
    document.getElementById('edit-schedule-modal').style.display = 'flex';
}

function closeEditModal() {
    document.getElementById('edit-schedule-modal').style.display = 'none';
}

async function saveScheduleEdit() {
    const timetableId = document.getElementById('edit-timetable-id').value;
    const newCourse = document.getElementById('edit-course').value.trim();
    const newRoom = document.getElementById('edit-room').value.trim();
    const newDay = document.getElementById('edit-day').value;
    const newStart = document.getElementById('edit-start').value;
    const newEnd = document.getElementById('edit-end').value;
    
    if (!newStart || !newEnd || !newCourse) {
        alert("Course, Start Time, and End Time are required.");
        return;
    }
    
    const payload = {
        action: "update",
        timetable_id: parseInt(timetableId),
        new_course_code: newCourse,
        new_room: newRoom,
        new_day_of_week: newDay,
        new_start_time: newStart + ":00",
        new_end_time: newEnd + ":00"
    };
    
    await addModificationDirect(payload);
    closeEditModal();
}

async function addModification(actionType, timetableId) {
    if (actionType === 'delete' && !confirm("Remove this slot from your personal schedule?")) return;
    
    const payload = {
        action: actionType,
        timetable_id: parseInt(timetableId)
    };
    
    await addModificationDirect(payload);
}

async function addModificationDirect(payload) {
    const authDataRaw = localStorage.getItem("dau_buddy_auth");
    if (!authDataRaw) return;
    const authData = JSON.parse(authDataRaw);
    
    try {
        const response = await fetch('/api/me/schedule/modifications', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authData.credential}`
            },
            body: JSON.stringify(payload)
        });
        
        if (!response.ok) {
            const err = await response.json();
            alert(err.detail || 'Failed to modify schedule. Check for conflicts.');
            return;
        }
        
        await loadWeeklyTimetable(authData);
    } catch (e) {
        console.error(e);
        alert('Failed to save modification.');
    }
}

async function deleteModification(modId, timetableId) {
    if (!confirm("Revert to the original official slot?")) return;
    
    const authDataRaw = localStorage.getItem("dau_buddy_auth");
    if (!authDataRaw) return;
    const authData = JSON.parse(authDataRaw);
    
    try {
        let url = '/api/me/schedule/modifications';
        if (modId) {
            url += `?modification_id=${modId}`;
        } else if (timetableId) {
            url += `?timetable_id=${timetableId}`;
        }
        
        const response = await fetch(url, {
            method: 'DELETE',
            headers: {
                'Authorization': `Bearer ${authData.credential}`
            }
        });
        
        if (!response.ok) {
            throw new Error('Failed to revert modification');
        }
        
        await loadWeeklyTimetable(authData);
    } catch (e) {
        console.error(e);
        alert('Failed to revert modification.');
    }
}
