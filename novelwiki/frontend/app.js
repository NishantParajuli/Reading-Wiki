document.addEventListener("DOMContentLoaded", () => {
    // ── Global State ──
    let activeChapterCeiling = 1.0;
    let maxScrapedChapter = 100.0;
    let activeTab = "chat"; // or "wiki"
    const apiBase = "/api";

    // ── Elements Cache ──
    const ceilingSlider = document.getElementById("ceiling-slider");
    const ceilingBadge = document.getElementById("ceiling-badge");
    const maxChapterLabel = document.getElementById("max-chapter-label");
    
    const tabPanes = document.querySelectorAll(".tab-pane");
    const navItems = document.querySelectorAll(".nav-item[data-tab]");
    
    // Chat selectors
    const chatHistory = document.getElementById("chat-history");
    const chatInput = document.getElementById("chat-input");
    const chatSendBtn = document.getElementById("chat-send-btn");
    
    // Wiki selectors
    const wikiGrid = document.getElementById("wiki-grid");
    const wikiSearchInput = document.getElementById("wiki-search-input");
    const wikiTypeSelect = document.getElementById("wiki-type-select");
    const entityDrawer = document.getElementById("entity-detail-drawer");
    const closeDrawerBtn = document.getElementById("close-drawer-btn");
    
    // Entity Drawer Content
    const detailName = document.getElementById("detail-name");
    const detailAliases = document.getElementById("detail-aliases");
    const detailTypeTag = document.getElementById("detail-type-tag");
    const detailFactsList = document.getElementById("detail-facts-list");
    const detailTimelineList = document.getElementById("detail-timeline-list");
    const detailRelationsList = document.getElementById("detail-relations-list");
    const profileTabBtns = document.querySelectorAll(".profile-tab-btn");
    const profilePanes = document.querySelectorAll(".profile-pane");
    
    // Admin elements
    const triggerScrapeBtn = document.getElementById("trigger-scrape-btn");
    const triggerChunkBtn = document.getElementById("trigger-chunk-btn");
    const adminModal = document.getElementById("admin-modal");
    const closeModalBtn = document.getElementById("close-modal-btn");
    const modalBody = document.getElementById("modal-body-content");

    let currentSelectedEntityId = null;

    // ── Init Operations ──
    async function loadMaxChapter() {
        try {
            const res = await fetch(`${apiBase}/meta/chapters`);
            if (!res.ok) throw new Error(`meta/chapters ${res.status}`);
            const data = await res.json();
            maxScrapedChapter = data.max_chapter || 1.0;
            ceilingSlider.max = maxScrapedChapter;
            ceilingSlider.min = data.min_chapter || 1.0;
            maxChapterLabel.textContent = `Ch ${maxScrapedChapter}`;
        } catch (e) {
            console.error("Could not load chapter range; defaulting.", e);
            maxScrapedChapter = 100.0;
            ceilingSlider.max = maxScrapedChapter;
            maxChapterLabel.textContent = `Ch ${maxScrapedChapter}`;
        }
    }
    
    loadMaxChapter();
    updateCeilingUI(1.0);

    // ── Ceiling Slider Controller ──
    ceilingSlider.addEventListener("input", (e) => {
        const val = parseFloat(e.target.value);
        updateCeilingUI(val);
    });

    function updateCeilingUI(value) {
        activeChapterCeiling = value;
        ceilingBadge.textContent = `Ch. ${value.toFixed(1)}`;
        
        // Refresh currently active Tab content
        if (activeTab === "wiki") {
            loadEntitiesList();
            if (entityDrawer.classList.contains("open") && currentSelectedEntityId) {
                openEntityProfile(currentSelectedEntityId);
            }
        }
    }

    // ── Tab Navigation ──
    navItems.forEach(item => {
        item.addEventListener("click", () => {
            const targetTab = item.getAttribute("data-tab");
            
            navItems.forEach(nav => nav.classList.remove("active"));
            item.classList.add("active");
            
            tabPanes.forEach(pane => pane.classList.remove("active"));
            document.getElementById(`tab-${targetTab}`).classList.add("active");
            
            activeTab = targetTab;
            
            if (activeTab === "wiki") {
                loadEntitiesList();
            }
        });
    });

    // ── Tab A: Lore Chatbot ──
    chatSendBtn.addEventListener("click", sendChatMessage);
    chatInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendChatMessage();
        }
    });

    async function sendChatMessage() {
        const text = chatInput.value.trim();
        if (!text) return;
        
        chatInput.value = "";
        
        // Render user message bubble
        appendChatBubble("user", `<p>${escapeHtml(text)}</p>`);
        
        // Render temporary assistant typing indicator bubble
        const loaderId = appendChatBubble("assistant typing", `
            <div class="typing-loader">
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
            </div>
        `);
        
        chatHistory.scrollTop = chatHistory.scrollHeight;

        try {
            const res = await fetch(`${apiBase}/ask`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    question: text,
                    chapter_ceiling: activeChapterCeiling
                })
            });
            
            if (!res.ok) throw new Error("Lore LLM failed to answer.");
            
            const data = await res.json();
            
            // Remove typing loader
            removeChatBubble(loaderId);
            
            // Render finalized markdown/cited text response
            let formattedAnswer = formatAnswerText(data.answer);
            if (Array.isArray(data.citations) && data.citations.length) {
                const items = data.citations.map(c =>
                    `<li><span class="cite-tag">[${escapeHtml(c.kind)} ${c.id}, Ch ${c.chapter}]</span> ${escapeHtml((c.snippet || "").slice(0, 140))}</li>`
                ).join("");
                formattedAnswer += `<div class="citations-footer"><strong>Sources</strong><ul>${items}</ul></div>`;
            }
            appendChatBubble("assistant", formattedAnswer);
            
        } catch (err) {
            removeChatBubble(loaderId);
            appendChatBubble("assistant error", `<p style="color: var(--accent-pink);"><i class="fa-solid fa-triangle-exclamation"></i> Error: ${err.message}</p>`);
        }
        
        chatHistory.scrollTop = chatHistory.scrollHeight;
    }

    function appendChatBubble(role, htmlContent) {
        const bubble = document.createElement("div");
        const bubbleId = "bubble-" + Date.now() + Math.random().toString(36).substr(2, 5);
        bubble.className = `chat-bubble ${role}`;
        bubble.id = bubbleId;
        
        const avatarIcon = role.includes("user") ? "fa-user-ninja" : "fa-robot";
        
        bubble.innerHTML = `
            <div class="bubble-avatar">
                <i class="fa-solid ${avatarIcon}"></i>
            </div>
            <div class="bubble-content">
                ${htmlContent}
            </div>
        `;
        
        chatHistory.appendChild(bubble);
        return bubbleId;
    }

    function removeChatBubble(id) {
        const node = document.getElementById(id);
        if (node) node.remove();
    }

    function formatAnswerText(text) {
        // Parse basic markdown elements: code blocks, lists, inline codes
        let formatted = escapeHtml(text);
        
        // Unescape bracket references so we can format citations
        // Match things like [Chunk 12, Chapter 5.0]
        formatted = formatted.replace(
            /\[Chunk\s+(\d+),\s+Chapter\s+(\d+(?:\.\d+)?)\]/g, 
            (match, chunkId, chapterNum) => {
                return `<span class="cite-tag" onclick="alert('Retrieved Chunk ID: ${chunkId}\\nChapter Revealed: ${chapterNum}')">[Chunk ${chunkId}, Ch ${chapterNum}]</span>`;
            }
        );

        // Convert lists
        formatted = formatted.replace(/^\s*-\s+(.+)$/gm, "<li>$1</li>");
        formatted = formatted.replace(/(<li>.+<\/li>)/s, "<ul>$1</ul>");

        // Convert linebreaks to <p>
        formatted = formatted.split("\n\n").map(para => {
            if (para.startsWith("<ul>") || para.startsWith("<li>")) return para;
            return `<p>${para.replace(/\n/g, "<br>")}</p>`;
        }).join("");

        return formatted;
    }

    // ── Tab B: Entity Directory Grid & Drawer ──
    wikiSearchInput.addEventListener("input", debounce(loadEntitiesList, 300));
    wikiTypeSelect.addEventListener("change", loadEntitiesList);
    closeDrawerBtn.addEventListener("click", () => entityDrawer.classList.remove("open"));

    async function loadEntitiesList() {
        const query = wikiSearchInput.value.trim();
        const type = wikiTypeSelect.value;
        
        try {
            const url = `${apiBase}/entities?ceiling=${activeChapterCeiling}&type=${type}&q=${encodeURIComponent(query)}`;
            const res = await fetch(url);
            if (!res.ok) throw new Error("Failed to load entities.");
            
            const entities = await res.json();
            renderEntitiesGrid(entities);
        } catch (e) {
            console.error(e);
            wikiGrid.innerHTML = `<p class="error-msg">Failed to load entities roster.</p>`;
        }
    }

    function renderEntitiesGrid(entities) {
        if (!entities || entities.length === 0) {
            wikiGrid.innerHTML = `<p class="text-secondary" style="grid-column: 1/-1; text-align: center; padding: 40px 0;">No lore entities discovered yet below Chapter ${activeChapterCeiling.toFixed(1)}.</p>`;
            return;
        }
        
        wikiGrid.innerHTML = "";
        entities.forEach(ent => {
            const card = document.createElement("div");
            card.className = `entity-card ${ent.type}`;
            
            const desc = ent.description || "No description recorded in this chapter.";
            
            card.innerHTML = `
                <div class="entity-card-header">
                    <h3 class="entity-card-title">${escapeHtml(ent.canonical_name)}</h3>
                    <span class="type-tag ${ent.type}">${ent.type}</span>
                </div>
                <p class="entity-card-desc">${escapeHtml(desc)}</p>
                <div class="entity-card-footer">
                    <span>Discovered: Ch ${ent.first_seen_chapter.toFixed(1)}</span>
                    <i class="fa-solid fa-arrow-right"></i>
                </div>
            `;
            
            card.addEventListener("click", () => openEntityProfile(ent.id));
            wikiGrid.appendChild(card);
        });
    }

    // ── Entity Profile Drawer ──
    async function openEntityProfile(entityId) {
        currentSelectedEntityId = entityId;
        entityDrawer.classList.add("open");
        
        // Reset subtabs
        switchProfileSubtab("facts");
        
        try {
            const res = await fetch(`${apiBase}/entity/${entityId}?ceiling=${activeChapterCeiling}`);
            if (!res.ok) throw new Error("Failed to fetch profile.");
            const profile = await res.json();
            
            // Populate basic header
            detailName.textContent = profile.canonical_name;
            detailTypeTag.textContent = profile.type;
            detailTypeTag.className = `type-tag ${profile.type}`;
            
            if (profile.aliases && profile.aliases.length > 0) {
                detailAliases.textContent = "Aliases: " + profile.aliases.join(", ");
            } else {
                detailAliases.textContent = "Aliases: None";
            }
            
            // 1. Render Profile Pane
            renderProfileFacts(profile.facts);
            
            // 2. Render Timeline Pane
            await loadAndRenderTimeline(entityId);
            
            // 3. Render Relationships Pane
            await loadAndRenderRelationships(entityId);
            
        } catch (e) {
            console.error(e);
            detailFactsList.innerHTML = `<p class="error-msg">Error loading profile data.</p>`;
        }
    }

    function renderProfileFacts(facts) {
        if (!facts || facts.length === 0) {
            detailFactsList.innerHTML = `<p class="text-secondary">No recorded lore facts available below this ceiling.</p>`;
            return;
        }
        
        detailFactsList.innerHTML = "";
        facts.forEach(fact => {
            const div = document.createElement("div");
            div.className = "fact-item";
            div.innerHTML = `
                <div class="fact-meta">
                    <span class="fact-type">${fact.fact_type || "trait"}</span>
                    <span>Discovered at Ch ${fact.chapter.toFixed(1)}</span>
                </div>
                <div class="fact-content">${escapeHtml(fact.content)}</div>
            `;
            detailFactsList.appendChild(div);
        });
    }

    async function loadAndRenderTimeline(entityId) {
        try {
            const res = await fetch(`${apiBase}/entity/${entityId}/timeline?ceiling=${activeChapterCeiling}`);
            if (!res.ok) throw new Error();
            const timeline = await res.json();
            
            if (!timeline || timeline.length === 0) {
                detailTimelineList.innerHTML = `<p class="text-secondary">Timeline empty at this chapter milestone.</p>`;
                return;
            }
            
            detailTimelineList.innerHTML = "";
            timeline.forEach(item => {
                const div = document.createElement("div");
                div.className = `timeline-item ${item.type}`;
                div.innerHTML = `
                    <div class="timeline-dot"></div>
                    <span class="timeline-chapter">Chapter ${item.chapter.toFixed(1)}</span>
                    <h4 class="timeline-title">${escapeHtml(item.label)}</h4>
                    <p class="timeline-desc">${escapeHtml(item.content)}</p>
                `;
                detailTimelineList.appendChild(div);
            });
        } catch (e) {
            detailTimelineList.innerHTML = `<p class="error-msg">Error loading timeline.</p>`;
        }
    }

    async function loadAndRenderRelationships(entityId) {
        try {
            const res = await fetch(`${apiBase}/entity/${entityId}/relationships?ceiling=${activeChapterCeiling}`);
            if (!res.ok) throw new Error();
            const rels = await res.json();
            
            if (!rels || rels.length === 0) {
                detailRelationsList.innerHTML = `<p class="text-secondary">No recorded relationships yet.</p>`;
                return;
            }
            
            detailRelationsList.innerHTML = "";
            rels.forEach(rel => {
                const div = document.createElement("div");
                div.className = "rel-item";
                
                const isSource = rel.source_id === entityId;
                const connectionName = isSource ? rel.target_name : rel.source_name;
                const dirArrow = rel.directed ? "→" : "↔";
                
                div.innerHTML = `
                    <div class="rel-left">
                        <span class="rel-target">${escapeHtml(connectionName)}</span>
                        <span class="rel-type">${escapeHtml(rel.relation_type)} ${dirArrow}</span>
                    </div>
                    <div class="rel-desc">${escapeHtml(rel.content || "Connection established.")}</div>
                `;
                detailRelationsList.appendChild(div);
            });
        } catch (e) {
            detailRelationsList.innerHTML = `<p class="error-msg">Error loading relationships.</p>`;
        }
    }

    // Drawer tabs
    profileTabBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            const target = btn.getAttribute("data-profile-tab");
            switchProfileSubtab(target);
        });
    });

    function switchProfileSubtab(targetTab) {
        profileTabBtns.forEach(b => b.classList.remove("active"));
        document.querySelector(`.profile-tab-btn[data-profile-tab="${targetTab}"]`).classList.add("active");
        
        profilePanes.forEach(p => p.classList.remove("active"));
        document.getElementById(`ptab-${targetTab}`).classList.add("active");
    }

    // ── Admin Actions Modal ──
    triggerScrapeBtn.addEventListener("click", () => {
        openAdminModal("scrape");
    });
    
    triggerChunkBtn.addEventListener("click", () => {
        openAdminModal("chunk");
    });
    
    closeModalBtn.addEventListener("click", () => adminModal.classList.remove("open"));

    function openAdminModal(action) {
        adminModal.classList.add("open");
        
        if (action === "scrape") {
            modalBody.innerHTML = `
                <form class="modal-form" id="scrape-form">
                    <div class="form-group">
                        <label for="start-url-input">Webnovel Starting Chapter URL</label>
                        <input type="url" id="start-url-input" required placeholder="https://fenrirealm.com/novel/.../chapter-1">
                    </div>
                    <div class="form-group">
                        <label for="max-ch-input">Max Chapters to Scrape (Optional)</label>
                        <input type="number" id="max-ch-input" min="1" placeholder="Leave empty for all">
                    </div>
                    <button type="submit" class="modal-submit-btn">Launch Polite Scraper</button>
                </form>
            `;
            
            document.getElementById("scrape-form").addEventListener("submit", async (e) => {
                e.preventDefault();
                const url = document.getElementById("start-url-input").value;
                const max = document.getElementById("max-ch-input").value;
                
                try {
                    const res = await fetch(`${apiBase}/admin/scrape`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                            start_url: url,
                            max_chapters: max ? parseInt(max) : null
                        })
                    });
                    if (res.ok) {
                        alert("Scraper job successfully triggered in the background!");
                        adminModal.classList.remove("open");
                    }
                } catch (err) {
                    alert("Failed to trigger scraper: " + err.message);
                }
            });
            
        } else if (action === "chunk") {
            modalBody.innerHTML = `
                <div style="display: flex; flex-direction: column; gap: 14px;">
                    <p style="font-size: 13px; color: var(--text-secondary); line-height: 1.5;">This executes the text chunking and embedding generation pipeline in the background. Fresh chapters will be split and embedded using OpenRouter vector engines.</p>
                    <button class="modal-submit-btn" id="run-pipeline-btn">Launch Pipeline Tasks</button>
                </div>
            `;
            
            document.getElementById("run-pipeline-btn").addEventListener("click", async () => {
                try {
                    // 1. Trigger chunking
                    await fetch(`${apiBase}/admin/chunk`, { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({}) });
                    // 2. Trigger embedding
                    await fetch(`${apiBase}/admin/embed`, { method: "POST" });
                    
                    alert("Chunking and Embedding pipelines scheduled successfully in the background!");
                    adminModal.classList.remove("open");
                } catch (err) {
                    alert("Failed to trigger pipelines: " + err.message);
                }
            });
        }
    }

    // ── Helper Utilities ──
    function escapeHtml(unsafe) {
        return unsafe
             .replace(/&/g, "&amp;")
             .replace(/</g, "&lt;")
             .replace(/>/g, "&gt;")
             .replace(/"/g, "&quot;")
             .replace(/'/g, "&#039;");
    }

    function debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    }
});
