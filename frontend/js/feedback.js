document.addEventListener("DOMContentLoaded", () => {
    // ── Feedback System HTML Injection ───────────────────────────────────────────
    if (!document.getElementById("feedback-modal")) {
        const modalHtml = `
            <!-- Feedback Modal -->
            <div id="feedback-modal" class="feedback-modal-overlay" style="display: none; flex-direction: column;">
                <div class="feedback-modal-content">
                    <div class="feedback-modal-header">
                        <h2>Share Your Feedback</h2>
                        <button id="close-feedback-btn" class="close-feedback-btn"><i class="fa-solid fa-xmark"></i></button>
                    </div>
                    <div class="feedback-modal-body">
                        <p style="font-size: 14px; color: #475569; margin-top: 0; margin-bottom: 24px; line-height: 1.5;">Help
                            us improve DAU Buddy by reporting bugs, requesting features, or sharing suggestions.</p>
                        <form id="feedback-form">
                            <div class="form-group">
                                <label for="feedback-category">Category <span style="color: red;">*</span></label>
                                <select id="feedback-category" required>
                                    <option value="" disabled selected>Select a category</option>
                                    <option value="Bug Report">🐞 Bug Report</option>
                                    <option value="Feature Request">✨ Feature Request</option>
                                    <option value="Improvement Suggestion">💡 Improvement Suggestion</option>
                                    <option value="General Feedback">💬 General Feedback</option>
                                </select>
                            </div>
                            <div class="form-group">
                                <label for="feedback-subject">Subject <span style="color: red;">*</span></label>
                                <input type="text" id="feedback-subject" placeholder="Brief summary of your feedback" required>
                            </div>
                            <div class="form-group">
                                <label for="feedback-description">Description <span style="color: red;">*</span></label>
                                <textarea id="feedback-description" rows="5"
                                    placeholder="Please provide detailed information..." required maxlength="1000"></textarea>
                                <div class="char-counter"><span id="char-count">0</span>/1000</div>
                            </div>
                            <div class="feedback-modal-footer">
                                <button type="button" id="cancel-feedback-btn" class="btn-cancel">Cancel</button>
                                <button type="submit" id="submit-feedback-btn" class="btn-submit">
                                    <span class="submit-text">Submit Feedback</span>
                                    <div class="loader" style="display: none;"></div>
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            </div>
        `;
        document.body.insertAdjacentHTML('beforeend', modalHtml);
    }
    
    if (!document.getElementById("toast-container")) {
        const toastHtml = `<div id="toast-container" class="toast-container"></div>`;
        document.body.insertAdjacentHTML('beforeend', toastHtml);
    }

    // ── Feedback System Logic ──────────────────────────────────────────────────

    const feedbackBtns = document.querySelectorAll(".nav-feedback-btn");
    const feedbackModal = document.getElementById("feedback-modal");
    const closeFeedbackBtn = document.getElementById("close-feedback-btn");
    const cancelFeedbackBtn = document.getElementById("cancel-feedback-btn");
    const feedbackForm = document.getElementById("feedback-form");
    const feedbackDesc = document.getElementById("feedback-description");
    const charCount = document.getElementById("char-count");
    const submitFeedbackBtn = document.getElementById("submit-feedback-btn");
    const submitText = submitFeedbackBtn?.querySelector(".submit-text");
    const loader = submitFeedbackBtn?.querySelector(".loader");
    const toastContainer = document.getElementById("toast-container");

    function showToast(message, type = "success") {
        if (!toastContainer) return;
        const toast = document.createElement("div");
        toast.className = `toast ${type}`;
        toast.innerHTML = type === "success"
            ? `<i class="fa-solid fa-circle-check"></i> <span>${message}</span>`
            : `<i class="fa-solid fa-circle-exclamation"></i> <span>${message}</span>`;

        toastContainer.appendChild(toast);

        setTimeout(() => {
            toast.style.animation = "slideInRight 0.3s ease-in reverse forwards";
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }

    if (feedbackBtns.length > 0 && feedbackModal) {
        feedbackBtns.forEach(btn => {
            btn.addEventListener("click", () => {
                feedbackModal.style.display = "flex";
                document.body.style.overflow = "hidden";
            });
        });

        const closeModal = () => {
            feedbackModal.style.display = "none";
            document.body.style.overflow = "";
            feedbackForm.reset();
            if (charCount) {
                charCount.textContent = "0";
                if (charCount.parentElement) charCount.parentElement.classList.remove("limit-reached");
            }
        };

        if (closeFeedbackBtn) closeFeedbackBtn.addEventListener("click", closeModal);
        if (cancelFeedbackBtn) cancelFeedbackBtn.addEventListener("click", closeModal);
        if (feedbackModal) feedbackModal.addEventListener("click", (e) => {
            if (e.target === feedbackModal) closeModal();
        });

        if (feedbackDesc && charCount) {
            if (feedbackDesc) feedbackDesc.addEventListener("input", (e) => {
                const len = e.target.value.length;
                charCount.textContent = len;
                if (len >= 1000) {
                    charCount.parentElement.classList.add("limit-reached");
                } else {
                    charCount.parentElement.classList.remove("limit-reached");
                }
            });
        }

        let isSubmittingFeedback = false;
        if (feedbackForm) {
            feedbackForm.addEventListener("submit", async (e) => {
                e.preventDefault();
                if (isSubmittingFeedback) return;

                const category = document.getElementById("feedback-category").value;
                const subject = document.getElementById("feedback-subject").value.trim();
                const description = feedbackDesc.value.trim();

                if (!category || !subject || !description) {
                    showToast("Please fill in all required fields.", "error");
                    return;
                }

                // Get current Google credential
                const authSession = JSON.parse(localStorage.getItem("dau_buddy_auth") || "{}");
                const currentCredential = authSession.credential;

                if (!currentCredential) {
                    showToast("Session not found. Please log in again.", "error");
                    return;
                }

                isSubmittingFeedback = true;
                submitFeedbackBtn.disabled = true;
                if (submitText) submitText.style.display = "none";
                if (loader) loader.style.display = "block";

                try {
                    const response = await fetch("/api/feedback", {
                        method: "POST",
                        headers: {
                            "Content-Type": "application/json"
                        },
                        body: JSON.stringify({ category, subject, description, credential: currentCredential })
                    });

                    if (response.ok) {
                        closeModal();
                        showToast("Thank you! Your feedback has been submitted.");
                    } else {
                        const errorData = await response.json();
                        showToast(errorData.detail || "Failed to submit feedback.", "error");
                    }
                } catch (error) {
                    console.error("Feedback error:", error);
                    showToast("An error occurred. Please try again.", "error");
                } finally {
                    isSubmittingFeedback = false;
                    submitFeedbackBtn.disabled = false;
                    if (submitText) submitText.style.display = "block";
                    if (loader) loader.style.display = "none";
                }
            });
        }
    }
});
