// YouTube-Instagram Bot Frontend — Live API Integration
const API = "http://localhost:8000";

// ── Boot ─────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
    setupNavigation();
    setupModals();
    setupTabs();
    setupFileUploads();
    setupSidebarToggle();
    refreshDashboard();
    setInterval(refreshDashboard, 15000); // auto-refresh every 15 s
});

// ── Navigation ────────────────────────────────────────────────────────────────
function setupNavigation() {
    document.querySelectorAll(".nav-item").forEach(item => {
        item.addEventListener("click", e => {
            e.preventDefault();
            document.querySelectorAll(".nav-item").forEach(n => n.classList.remove("active"));
            document.querySelectorAll(".page").forEach(p => p.classList.remove("active"));
            item.classList.add("active");
            const pageId = item.getAttribute("data-page");
            document.getElementById(pageId)?.classList.add("active");
            document.getElementById("page-title").textContent =
                item.querySelector("span")?.textContent ?? pageId;
        });
    });
}

// ── Modals ────────────────────────────────────────────────────────────────────
function setupModals() {
    document.querySelectorAll(".close-modal").forEach(btn =>
        btn.addEventListener("click", closeModal));
}
function closeModal() {
    document.querySelectorAll(".modal").forEach(m => m.style.display = "none");
}
function showUploadModal()    { document.getElementById("uploadModal").style.display = "flex"; }
function showInstagramModal() { document.getElementById("instagramModal").style.display = "flex"; }
function showRumbleModal()    { document.getElementById("rumbleModal").style.display = "flex"; }

// ── Tabs ──────────────────────────────────────────────────────────────────────
function setupTabs() {
    document.querySelectorAll(".tab-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            const group = btn.closest(".tab-group") ?? btn.parentElement;
            group.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            const tabId = btn.getAttribute("data-tab");
            document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
            document.getElementById(tabId)?.classList.add("active");
        });
    });
}

// ── File uploads ──────────────────────────────────────────────────────────────
function setupFileUploads() {
    document.querySelectorAll(".file-upload").forEach(el => {
        el.addEventListener("dragover", e => { e.preventDefault(); el.classList.add("dragover"); });
        el.addEventListener("dragleave", () => el.classList.remove("dragover"));
        el.addEventListener("drop", e => {
            e.preventDefault(); el.classList.remove("dragover");
            const f = e.dataTransfer.files[0];
            if (f) el.querySelector("span").textContent = f.name;
        });
        el.addEventListener("click", () => el.querySelector("input")?.click());
    });
}

// ── Sidebar toggle ────────────────────────────────────────────────────────────
function setupSidebarToggle() {
    document.querySelector(".menu-toggle")?.addEventListener("click", () =>
        document.querySelector(".sidebar")?.classList.toggle("open"));
}

// ── Dashboard refresh (live API) ──────────────────────────────────────────────
async function refreshDashboard() {
    await Promise.all([fetchStats(), fetchRateLimits(), fetchStatus()]);
    renderActivity();
}

async function fetchStats() {
    try {
        const res  = await fetch(`${API}/api/dashboard`);
        const data = await res.json();
        setText("youtube-count",   data.youtube   ?? 0);
        setText("instagram-count", data.instagram ?? 0);
        setText("rumble-count",    data.rumble    ?? 0);
        setText("follower-count",  fmtNum(data.followers ?? 0));
    } catch { /* API unreachable — keep last values */ }
}

async function fetchRateLimits() {
    try {
        const res  = await fetch(`${API}/api/rate-limits`);
        const data = await res.json();
        setText("rl-instagram", `${data.instagram?.current ?? 0} / ${data.instagram?.max_requests ?? 15} per hr`);
        setText("rl-youtube",   `${data.youtube?.current   ?? 0} / ${data.youtube?.max_requests   ?? 10} per hr`);
        setText("rl-rumble",    `${data.rumble?.current    ?? 0} / ${data.rumble?.max_requests    ?? 50} per hr`);
    } catch {}
}

async function fetchStatus() {
    try {
        const res  = await fetch(`${API}/api/status`);
        const data = await res.json();
        const dot  = document.querySelector(".status-active");
        if (dot) dot.style.color = data.system === "operational" ? "var(--success)" : "var(--danger)";
        document.querySelector(".status-indicator span").textContent =
            data.system === "operational" ? "System Active" : "System Error";
        updateStatusList(data);
    } catch {
        document.querySelector(".status-indicator span").textContent = "API Offline";
    }
}

function updateStatusList(data) {
    const items = {
        "status-storage":    data.storage         === "connected"   ? "Connected"   : "Error",
        "status-api":        data.api_connections === "active"      ? "Active"      : "Inactive",
        "status-ratelimits": data.rate_limits     === "active"      ? "Active"      : "Inactive",
    };
    for (const [id, text] of Object.entries(items)) {
        const el = document.getElementById(id);
        if (el) { el.textContent = text; el.className = text === "Error" || text === "Inactive" ? "text-danger" : "text-success"; }
    }
}

function renderActivity() {
    const list = document.getElementById("activity-list");
    if (!list) return;
    const activities = [
        { icon: "fa-upload",     title: "YouTube Short queued for upload",    time: "just now",    color: "#ff0000" },
        { icon: "fa-image",      title: "Instagram Reel posted",              time: "2 min ago",   color: "#e1306c" },
        { icon: "fa-heart",      title: "Auto-liked 15 posts",                time: "10 min ago",  color: "#e1306c" },
        { icon: "fa-user-plus",  title: "Followed 20 users via #trending",    time: "25 min ago",  color: "#6366f1" },
        { icon: "fa-eye",        title: "Generated 50 Rumble views",          time: "40 min ago",  color: "#ff6600" },
    ];
    list.innerHTML = activities.map(a => `
        <div class="activity-item">
            <div class="activity-icon" style="background:${a.color}">
                <i class="fas ${a.icon}"></i>
            </div>
            <div class="activity-info">
                <div class="activity-title">${a.title}</div>
                <div class="activity-time">${a.time}</div>
            </div>
        </div>`).join("");
}

// ── Actions ───────────────────────────────────────────────────────────────────
async function uploadVideo() {
    const title = document.getElementById("video-title")?.value?.trim();
    const type  = document.getElementById("video-type")?.value ?? "video";
    if (!title) { showToast("Please enter a video title", "warning"); return; }
    const btn = event.target; btn.disabled = true; btn.textContent = "Uploading…";
    try {
        const res  = await post("/api/youtube/upload", { title, type });
        showToast(`Queued! ID: ${res.video_id}`, "success");
        closeModal();
    } catch (e) { showToast("Upload failed: " + e.message, "error"); }
    finally { btn.disabled = false; btn.textContent = "Upload"; }
}

async function postInstagram() {
    const caption = document.getElementById("ig-caption")?.value?.trim() ?? "";
    const type    = document.getElementById("ig-type")?.value ?? "image";
    const btn = event.target; btn.disabled = true; btn.textContent = "Posting…";
    try {
        const res = await post("/api/instagram/post", { caption, type });
        showToast(`Posted! ID: ${res.post_id}`, "success");
        closeModal();
    } catch (e) { showToast("Post failed: " + e.message, "error"); }
    finally { btn.disabled = false; btn.textContent = "Post"; }
}

async function generateRumbleViews() {
    const url   = document.getElementById("rumble-url")?.value?.trim();
    const views = parseInt(document.getElementById("rumble-views")?.value ?? "100");
    if (!url) { showToast("Please enter a Rumble video URL", "warning"); return; }
    const btn = event.target; btn.disabled = true; btn.textContent = "Starting…";
    try {
        const res = await post("/api/rumble/views", { video_url: url, views });
        showToast(`View generation started — target: ${res.views_target}`, "success");
        closeModal();
    } catch (e) { showToast("Failed: " + e.message, "error"); }
    finally { btn.disabled = false; btn.textContent = "Start"; }
}

async function executeFollow() {
    const tag  = document.getElementById("follow-tag")?.value?.trim();
    const max  = parseInt(document.getElementById("follow-max")?.value ?? "20");
    if (!tag) { showToast("Please enter a hashtag", "warning"); return; }
    try {
        const res = await post("/api/engagement/follow", { tag, count: max });
        showToast(`Follow campaign started: ${res.followed} follows`, "success");
    } catch (e) { showToast("Failed: " + e.message, "error"); }
}

async function executeUnfollow() {
    try {
        const res = await post("/api/engagement/follow", { action: "unfollow", count: 50 });
        showToast("Unfollow campaign started", "success");
    } catch (e) { showToast("Failed: " + e.message, "error"); }
}

async function executeLike() {
    try {
        const res = await post("/api/engagement/follow", { action: "like", count: 30 });
        showToast("Like campaign started", "success");
    } catch (e) { showToast("Failed: " + e.message, "error"); }
}

async function scheduleBatchUpload() {
    const time = document.getElementById("batch-time")?.value;
    if (!time) { showToast("Please set a schedule time", "warning"); return; }
    try {
        const res = await post("/api/scheduler/schedule", { scheduled_time: time, type: "batch_upload" });
        showToast(`Scheduled! Job ID: ${res.job_id}`, "success");
    } catch (e) { showToast("Failed: " + e.message, "error"); }
}

async function autoSchedulePosts() {
    const interval = document.getElementById("post-interval")?.value ?? "8";
    try {
        const res = await post("/api/scheduler/schedule", { interval_hours: parseInt(interval), type: "auto_post" });
        showToast(`Auto-schedule set! Job ID: ${res.job_id}`, "success");
    } catch (e) { showToast("Failed: " + e.message, "error"); }
}

// ── Helpers ───────────────────────────────────────────────────────────────────
async function post(path, body) {
    const res = await fetch(`${API}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
}

function setText(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
}

function fmtNum(n) {
    if (n >= 1000) return (n / 1000).toFixed(1) + "K";
    return n.toString();
}

function showToast(msg, type = "info") {
    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    toast.textContent = msg;
    document.body.appendChild(toast);
    setTimeout(() => toast.classList.add("show"), 10);
    setTimeout(() => { toast.classList.remove("show"); setTimeout(() => toast.remove(), 300); }, 3500);
}

// ── Logout ────────────────────────────────────────────────────────────────────
document.querySelector(".logout-btn")?.addEventListener("click", () => {
    if (confirm("Are you sure you want to logout?")) showToast("Logged out", "info");
});

// ── Instagram Credentials ──────────────────────────────────────────────────

async function checkInstagramStatus() {
    try {
        const res  = await fetch(`${API}/api/instagram/status`);
        const data = await res.json();
        const banner = document.getElementById("ig-status-banner");
        const badge  = document.getElementById("ig-mode-badge");

        if (data.configured && data.mode === "live") {
            if (banner) {
                banner.style.background = "#d1fae5";
                banner.style.color      = "#065f46";
                banner.innerHTML = `<i class="fas fa-check-circle"></i> <strong>Live Mode</strong> — Connected as user ID ${data.user_id}`;
            }
            if (badge) { badge.textContent = "LIVE"; badge.style.background = "var(--success)"; }
        } else {
            if (badge) { badge.textContent = "SIM"; badge.style.background = "var(--warning)"; }
        }

        // Update daily stats
        if (data.daily_stats) {
            setText("eng-follows-today",    data.daily_stats.follows_today    ?? 0);
            setText("eng-follows-remaining",data.daily_stats.follows_remaining ?? 150);
            setText("eng-likes-today",      data.daily_stats.likes_today      ?? 0);
            setText("eng-unfollows-today",  data.daily_stats.unfollows_today  ?? 0);
        }
    } catch {}
}

async function saveInstagramCredentials() {
    const userId = document.getElementById("ig-user-id")?.value?.trim();
    const token  = document.getElementById("ig-access-token")?.value?.trim();
    if (!userId || !token) {
        showToast("Please fill in both User ID and Access Token", "warning");
        return;
    }
    try {
        const res = await post("/api/instagram/credentials", {
            instagram_user_id: userId,
            instagram_access_token: token,
        });
        showToast(res.message, "success");
        await checkInstagramStatus();
    } catch (e) {
        showToast("Failed to save credentials: " + e.message, "error");
    }
}

async function validateInstagramToken() {
    const result = document.getElementById("ig-validate-result");
    if (result) result.style.display = "none";
    try {
        const data = await (await fetch(`${API}/api/instagram/validate-token`, { method: "POST" })).json();
        if (result) {
            result.style.display = "block";
            result.style.background = "#d1fae5";
            result.style.color = "#065f46";
            result.style.padding = "12px";
            result.style.borderRadius = "8px";
            result.innerHTML = `
                <strong><i class="fas fa-check-circle"></i> Token Valid</strong><br>
                Name: ${data.name}<br>
                Followers: ${data.followers?.toLocaleString() ?? "—"}<br>
                Following: ${data.following?.toLocaleString() ?? "—"}<br>
                Posts: ${data.media_count ?? "—"}
            `;
        }
        showToast(`Token valid — ${data.name}`, "success");
    } catch (e) {
        const detail = e.message || "Invalid token";
        if (result) {
            result.style.display = "block";
            result.style.background = "#fee2e2";
            result.style.color = "#991b1b";
            result.style.padding = "12px";
            result.style.borderRadius = "8px";
            result.innerHTML = `<strong><i class="fas fa-times-circle"></i> Token Invalid</strong><br>${detail}`;
        }
        showToast("Token validation failed", "error");
    }
}

// ── Updated engagement actions ─────────────────────────────────────────────

async function executeFollow() {
    const tag   = document.getElementById("follow-tag")?.value?.trim();
    const max   = parseInt(document.getElementById("follow-max")?.value ?? "20");
    if (!tag) { showToast("Please enter a hashtag", "warning"); return; }

    const btn = document.querySelector("#tab-follow .btn");
    if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Running…'; }

    try {
        const res = await post("/api/engagement/follow", { action: "follow", tag, count: max });
        const mode = res.mode === "live" ? "🟢 LIVE" : "🟡 SIM";
        showToast(
            `${mode} Followed: ${res.followed ?? 0}  Skipped: ${res.skipped_already_followed ?? 0}  Errors: ${res.errors?.length ?? 0}`,
            res.mode === "live" ? "success" : "info"
        );
        if (res.message) showToast(res.message, "warning");
        await checkInstagramStatus();
    } catch (e) {
        showToast("Failed: " + e.message, "error");
    } finally {
        if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-user-plus"></i> Start Following'; }
    }
}

async function executeUnfollow() {
    const btn = document.querySelector("#tab-unfollow .btn");
    if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Running…'; }
    try {
        const res = await post("/api/engagement/follow", { action: "unfollow", count: 50 });
        const mode = res.mode === "live" ? "🟢 LIVE" : "🟡 SIM";
        showToast(`${mode} Unfollowed: ${res.unfollowed ?? 0}`, res.mode === "live" ? "success" : "info");
        if (res.message) showToast(res.message, "warning");
        await checkInstagramStatus();
    } catch (e) {
        showToast("Failed: " + e.message, "error");
    } finally {
        if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-user-minus"></i> Unfollow Non-Reciprocals'; }
    }
}

async function executeLike() {
    const tag = document.getElementById("follow-tag")?.value?.trim() || "viral";
    const btn = document.querySelector("#tab-like .btn");
    if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Running…'; }
    try {
        const res = await post("/api/engagement/like", { tag, count: 30 });
        const mode = res.mode === "live" ? "🟢 LIVE" : "🟡 SIM";
        showToast(`${mode} Liked: ${res.liked ?? 0}`, res.mode === "live" ? "success" : "info");
        if (res.message) showToast(res.message, "warning");
        await checkInstagramStatus();
    } catch (e) {
        showToast("Failed: " + e.message, "error");
    } finally {
        if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-heart"></i> Start Liking'; }
    }
}

// Run Instagram status check on load and every 30s
setTimeout(checkInstagramStatus, 1000);
setInterval(checkInstagramStatus, 30000);


// ════════════════════════════════════════════════════════════════════════════
//  YouTube — Credentials, Status, Upload, Like, Comment, Subscribe, Engage
// ════════════════════════════════════════════════════════════════════════════

function extractVideoId(input) {
    // Accept bare ID or full URL youtube.com/watch?v=ID or youtu.be/ID
    if (!input) return "";
    const m = input.match(/(?:v=|youtu\.be\/)([A-Za-z0-9_-]{11})/);
    return m ? m[1] : input.trim();
}

async function checkYouTubeStatus() {
    try {
        const res  = await fetch(`${API}/api/youtube/status`);
        const data = await res.json();
        const badge  = document.getElementById("yt-mode-badge");
        const banner = document.getElementById("yt-status-banner");

        if (data.configured && data.mode === "live") {
            if (badge)  { badge.textContent = "LIVE"; badge.style.background = "var(--success)"; }
            if (banner) {
                banner.style.background = "#d1fae5"; banner.style.color = "#065f46";
                banner.innerHTML = `<i class="fas fa-check-circle"></i> <strong>Live Mode</strong> — YouTube API connected`;
            }
            // Load channel card
            loadYouTubeChannel();
        } else {
            if (badge)  { badge.textContent = "SIM"; badge.style.background = "var(--warning)"; }
        }

        // Update stats strip
        const s = data.daily_stats;
        if (s) {
            setText("yt-quota-used",      s.quota_used     ?? 0);
            setText("yt-quota-remaining", (s.quota_remaining ?? 10000).toLocaleString());
            setText("yt-uploads-today",   s.uploads_today   ?? 0);
            setText("yt-likes-today",     s.likes_today     ?? 0);
            setText("yt-subs-today",      s.subscribes_today ?? 0);
        }
    } catch {}
}

async function loadYouTubeChannel() {
    try {
        const data = await (await fetch(`${API}/api/youtube/channel`)).json();
        if (data.error) return;
        const card = document.getElementById("yt-channel-card");
        if (card) card.style.display = "block";
        setText("yt-ch-title",  data.title    ?? "—");
        setText("yt-ch-subs",   fmtNum(data.subscriber_count ?? 0));
        setText("yt-ch-views",  fmtNum(data.view_count       ?? 0));
        setText("yt-ch-videos", data.video_count ?? 0);
    } catch {}
}

async function saveYouTubeCredentials() {
    const clientId     = document.getElementById("yt-client-id")?.value?.trim();
    const clientSecret = document.getElementById("yt-client-secret")?.value?.trim();
    const refreshToken = document.getElementById("yt-refresh-token")?.value?.trim();
    const channelId    = document.getElementById("yt-channel-id-input")?.value?.trim() ?? "";

    if (!clientId || !clientSecret || !refreshToken) {
        showToast("Please fill in Client ID, Client Secret, and Refresh Token", "warning");
        return;
    }
    try {
        const res = await post("/api/youtube/credentials", {
            client_id: clientId, client_secret: clientSecret,
            refresh_token: refreshToken, channel_id: channelId,
        });
        showToast(res.message, "success");
        await checkYouTubeStatus();
    } catch (e) {
        showToast("Failed to save: " + e.message, "error");
    }
}

async function validateYouTubeToken() {
    const result = document.getElementById("yt-validate-result");
    if (result) result.style.display = "none";
    try {
        const data = await (await fetch(`${API}/api/youtube/validate-token`, { method: "POST" })).json();
        if (result) {
            result.style.display = "block";
            result.style.padding = "12px";
            result.style.borderRadius = "8px";
            result.style.background = data.error ? "#fee2e2" : "#d1fae5";
            result.style.color      = data.error ? "#991b1b" : "#065f46";
            result.innerHTML = data.error
                ? `<strong><i class="fas fa-times-circle"></i> Invalid</strong><br>${data.error}`
                : `<strong><i class="fas fa-check-circle"></i> Valid</strong><br>
                   Channel: ${data.title}<br>
                   Subscribers: ${data.subscriber_count?.toLocaleString() ?? "—"}<br>
                   Total Views: ${data.view_count?.toLocaleString() ?? "—"}<br>
                   Videos: ${data.video_count ?? "—"}`;
        }
        if (!data.error) showToast(`Connected — ${data.title}`, "success");
    } catch (e) {
        if (result) {
            result.style.display = "block"; result.style.background = "#fee2e2";
            result.style.color = "#991b1b"; result.style.padding = "12px";
            result.style.borderRadius = "8px";
            result.innerHTML = `<strong>Validation failed</strong><br>${e.message}`;
        }
        showToast("Token validation failed", "error");
    }
}

// ── Upload ────────────────────────────────────────────────────────────────────

async function ytUpload() {
    const title   = document.getElementById("yt-upload-title")?.value?.trim();
    const desc    = document.getElementById("yt-upload-desc")?.value?.trim() ?? "";
    const tagsRaw = document.getElementById("yt-upload-tags")?.value?.trim() ?? "";
    const type    = document.getElementById("yt-upload-type")?.value ?? "video";
    const privacy = document.getElementById("yt-upload-privacy")?.value ?? "public";
    if (!title) { showToast("Please enter a video title", "warning"); return; }
    const tags = tagsRaw.split(",").map(t => t.trim()).filter(Boolean);
    const btn = event.target; btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Uploading…';
    try {
        const res = await post("/api/youtube/upload", { title, description: desc, tags, video_type: type, privacy });
        const mode = res.mode === "live" ? "🔴 LIVE" : "🟡 SIM";
        showToast(`${mode} ${res.message}`, res.mode === "live" ? "success" : "info");
        await checkYouTubeStatus();
    } catch (e) { showToast("Upload failed: " + e.message, "error"); }
    finally { btn.disabled = false; btn.innerHTML = '<i class="fas fa-upload"></i> Upload'; }
}

// ── Search & Engage ───────────────────────────────────────────────────────────

async function ytSearchEngage() {
    const query      = document.getElementById("yt-search-query")?.value?.trim();
    const maxVideos  = parseInt(document.getElementById("yt-search-max")?.value ?? "10");
    const doLike     = document.getElementById("yt-do-like")?.checked ?? true;
    const doComment  = document.getElementById("yt-do-comment")?.checked ?? false;
    const doSub      = document.getElementById("yt-do-subscribe")?.checked ?? false;
    const commentTxt = document.getElementById("yt-comment-text")?.value?.trim() ?? "Great video! 🔥";
    if (!query) { showToast("Please enter a search keyword", "warning"); return; }

    const btn = event.target; btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Engaging…';
    try {
        const res = await post("/api/youtube/search-engage", {
            query, max_videos: maxVideos,
            do_like: doLike, do_comment: doComment, do_subscribe: doSub,
            comment_text: commentTxt,
        });
        const mode = res.mode === "live" ? "🔴 LIVE" : "🟡 SIM";
        showToast(
            `${mode} Found: ${res.videos_found} | Liked: ${res.liked} | Commented: ${res.commented} | Subscribed: ${res.subscribed}`,
            res.mode === "live" ? "success" : "info"
        );
        if (res.message) showToast(res.message, "warning");
        await checkYouTubeStatus();
    } catch (e) { showToast("Failed: " + e.message, "error"); }
    finally { btn.disabled = false; btn.innerHTML = '<i class="fas fa-search"></i> Search &amp; Engage'; }
}

// ── Like ──────────────────────────────────────────────────────────────────────

async function ytLike() {
    const raw = document.getElementById("yt-like-id")?.value?.trim();
    const vid = extractVideoId(raw);
    if (!vid) { showToast("Please enter a video ID or URL", "warning"); return; }
    const btn = event.target; btn.disabled = true;
    try {
        const res = await post("/api/youtube/like", { video_id: vid });
        const mode = res.mode === "live" ? "🔴 LIVE" : "🟡 SIM";
        showToast(`${mode} ${res.liked ? "Liked!" : "Skipped — " + (res.errors[0] ?? "cap reached")}`,
                  res.liked ? "success" : "warning");
        if (res.message) showToast(res.message, "info");
        await checkYouTubeStatus();
    } catch (e) { showToast("Failed: " + e.message, "error"); }
    finally { btn.disabled = false; }
}

// ── Comment ───────────────────────────────────────────────────────────────────

async function ytComment() {
    const raw  = document.getElementById("yt-comment-vid-id")?.value?.trim();
    const text = document.getElementById("yt-comment-body")?.value?.trim();
    const vid  = extractVideoId(raw);
    if (!vid || !text) { showToast("Please fill in video ID and comment", "warning"); return; }
    const btn = event.target; btn.disabled = true;
    try {
        const res = await post("/api/youtube/comment", { video_id: vid, text });
        const mode = res.mode === "live" ? "🔴 LIVE" : "🟡 SIM";
        showToast(`${mode} ${res.commented ? "Comment posted!" : "Skipped — " + (res.errors[0] ?? "")}`,
                  res.commented ? "success" : "warning");
        if (res.message) showToast(res.message, "info");
        await checkYouTubeStatus();
    } catch (e) { showToast("Failed: " + e.message, "error"); }
    finally { btn.disabled = false; }
}

// ── Subscribe ─────────────────────────────────────────────────────────────────

async function ytSubscribe() {
    const channelId = document.getElementById("yt-sub-channel-id")?.value?.trim();
    if (!channelId) { showToast("Please enter a channel ID", "warning"); return; }
    const btn = event.target; btn.disabled = true;
    try {
        const res = await post("/api/youtube/subscribe", { channel_id: channelId });
        const mode = res.mode === "live" ? "🔴 LIVE" : "🟡 SIM";
        showToast(`${mode} ${res.subscribed ? "Subscribed!" : "Skipped — " + (res.errors[0] ?? "")}`,
                  res.subscribed ? "success" : "warning");
        if (res.message) showToast(res.message, "info");
        await checkYouTubeStatus();
    } catch (e) { showToast("Failed: " + e.message, "error"); }
    finally { btn.disabled = false; }
}

// Toggle comment text field visibility
document.getElementById("yt-do-comment")?.addEventListener("change", function() {
    const el = document.getElementById("yt-comment-text-group");
    if (el) el.style.display = this.checked ? "block" : "none";
});

// Run YouTube status check on load and every 30s
setTimeout(checkYouTubeStatus, 1500);
setInterval(checkYouTubeStatus, 30000);

// ════════════════════════════════════════════════════════════════════════════
//  ✨  MAGIC — one-click YouTube + Instagram automation
// ════════════════════════════════════════════════════════════════════════════

let _magicPollTimer = null;
let _currentMagicJobId = null;

async function runMagic() {
    const ytUrl  = document.getElementById("magic-yt-url")?.value?.trim();
    const igId   = document.getElementById("magic-ig-id")?.value?.trim();

    if (!ytUrl)  { showToast("Please enter a YouTube video URL", "warning"); return; }
    if (!igId)   { showToast("Please enter an Instagram username or hashtag", "warning"); return; }

    const btn = document.getElementById("magic-go-btn");
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> Starting Magic…';

    const payload = {
        youtube_url:    ytUrl,
        instagram_id:   igId.replace(/^@/, ""),
        yt_like:        document.getElementById("mt-yt-like")?.checked    ?? true,
        yt_comment:     document.getElementById("mt-yt-comment")?.checked ?? true,
        yt_subscribe:   document.getElementById("mt-yt-subscribe")?.checked ?? true,
        ig_follow:      document.getElementById("mt-ig-follow")?.checked  ?? true,
        ig_like:        document.getElementById("mt-ig-like")?.checked    ?? true,
        yt_max_engage:  parseInt(document.getElementById("magic-yt-max")?.value        ?? "10"),
        ig_max_follow:  parseInt(document.getElementById("magic-ig-follow-max")?.value ?? "20"),
        ig_max_like:    parseInt(document.getElementById("magic-ig-like-max")?.value   ?? "20"),
        comment_text:   document.getElementById("magic-comment")?.value ?? "Amazing content! 🔥",
    };

    try {
        const res = await post("/api/magic/run", payload);
        _currentMagicJobId = res.job_id;

        // Show progress card
        document.getElementById("magic-progress-card").style.display = "block";
        document.getElementById("magic-job-id-badge").textContent = res.job_id;
        document.getElementById("magic-log").innerHTML = "";
        document.getElementById("magic-status-label").textContent = "Running…";
        document.getElementById("magic-spinner").style.display = "inline";
        document.getElementById("magic-results-summary").style.display = "none";

        // Scroll to progress card
        document.getElementById("magic-progress-card").scrollIntoView({ behavior: "smooth" });

        // Start polling
        if (_magicPollTimer) clearInterval(_magicPollTimer);
        _magicPollTimer = setInterval(() => pollMagicJob(res.job_id), 1500);

    } catch (e) {
        showToast("Failed to start Magic: " + e.message, "error");
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-magic"></i> Run Magic';
    }
}

async function pollMagicJob(jobId) {
    try {
        const data = await (await fetch(`${API}/api/magic/status/${jobId}`)).json();

        // Render live log lines
        const logEl = document.getElementById("magic-log");
        if (logEl) {
            logEl.innerHTML = data.progress.map(line => {
                let cls = "log-step";
                if (line.includes("✅")) cls = "log-ok";
                else if (line.includes("⚠️")) cls = "log-warn";
                else if (line.includes("❌")) cls = "log-error";
                return `<div class="${cls}">${escapeHtml(line)}</div>`;
            }).join("");
            logEl.scrollTop = logEl.scrollHeight;
        }

        if (data.status === "completed" || data.status === "failed") {
            clearInterval(_magicPollTimer);
            _magicPollTimer = null;

            const spinner = document.getElementById("magic-spinner");
            const label   = document.getElementById("magic-status-label");
            const btn     = document.getElementById("magic-go-btn");

            if (data.status === "completed") {
                if (spinner) spinner.className = "fas fa-check-circle";
                if (spinner) spinner.style.color = "var(--success)";
                if (label)   label.textContent = "Magic Complete! 🎉";
                showToast("✨ Magic completed successfully!", "success");
                renderMagicSummary(data.results);
            } else {
                if (spinner) spinner.className = "fas fa-times-circle";
                if (spinner) spinner.style.color = "var(--danger)";
                if (label)   label.textContent = "Magic Failed";
                showToast("Magic failed: " + (data.error || "unknown error"), "error");
            }

            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '<i class="fas fa-magic"></i> Run Magic Again';
            }

            loadMagicHistory();
            refreshDashboard();
        }
    } catch (e) {
        // Network error — keep polling
        console.warn("Poll error:", e);
    }
}

function renderMagicSummary(results) {
    const el = document.getElementById("magic-results-summary");
    if (!el) return;

    const yt  = results.yt_like       || {};
    const ytc = results.yt_comment    || {};
    const yts = results.yt_subscribe  || {};
    const yte = results.yt_search_engage || {};
    const igf = results.ig_follow     || {};
    const igl = results.ig_like       || {};
    const vs  = results.video_stats   || {};

    const mode = yt.mode || yte.mode || igf.mode || "simulation";
    const modeBadge = mode === "live"
        ? `<span style="background:#10b981;color:white;padding:2px 10px;border-radius:20px;font-size:12px;font-weight:600">🔴 LIVE</span>`
        : `<span style="background:#f59e0b;color:white;padding:2px 10px;border-radius:20px;font-size:12px;font-weight:600">🟡 SIM</span>`;

    el.style.display = "block";
    el.innerHTML = `
        <div style="border-top:1px solid var(--border);padding-top:16px">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
                <h4 style="font-weight:600">Results Summary</h4>
                ${modeBadge}
            </div>
            ${vs.title ? `<p style="font-size:13px;color:var(--gray);margin-bottom:12px">📹 <strong>${escapeHtml(vs.title)}</strong> — ${(vs.view_count||0).toLocaleString()} views</p>` : ""}
            <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:10px">
                ${summaryCard("👍 YT Like",      yt.liked       ? "Done"   : "Skipped", yt.liked      ? "#10b981" : "#94a3b8")}
                ${summaryCard("💬 YT Comment",   ytc.commented  ? "Done"   : "Skipped", ytc.commented  ? "#10b981" : "#94a3b8")}
                ${summaryCard("🔔 YT Subscribe", yts.subscribed ? "Done"   : "Skipped", yts.subscribed ? "#10b981" : "#94a3b8")}
                ${summaryCard("🔎 Similar vids", (yte.liked||0)+" liked", "#6366f1")}
                ${summaryCard("👥 IG Follows",   (igf.followed||0)+" users", "#e1306c")}
                ${summaryCard("❤️  IG Likes",    (igl.liked||0)+" posts",   "#e1306c")}
            </div>
        </div>`;
}

function summaryCard(label, value, color) {
    return `<div style="background:white;border:1px solid var(--border);border-radius:10px;padding:12px;text-align:center">
        <div style="font-size:12px;color:var(--gray);margin-bottom:4px">${label}</div>
        <div style="font-size:16px;font-weight:700;color:${color}">${value}</div>
    </div>`;
}

async function loadMagicHistory() {
    try {
        const data = await (await fetch(`${API}/api/magic/jobs`)).json();
        const histEl = document.getElementById("magic-history");
        const listEl = document.getElementById("magic-history-list");
        if (!histEl || !listEl || !data.jobs?.length) return;

        histEl.style.display = "block";
        listEl.innerHTML = data.jobs.map(j => {
            const statusColor = j.status === "completed" ? "#10b981" : j.status === "failed" ? "#ef4444" : "#f59e0b";
            const statusIcon  = j.status === "completed" ? "✅" : j.status === "failed" ? "❌" : "⏳";
            return `<div style="display:flex;align-items:center;gap:12px;padding:12px;border-bottom:1px solid var(--border);font-size:13px">
                <span style="font-size:16px">${statusIcon}</span>
                <div style="flex:1;min-width:0">
                    <div style="font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${escapeHtml(j.youtube_url)}">${escapeHtml(j.youtube_url)}</div>
                    <div style="color:var(--gray);font-size:12px">@${escapeHtml(j.instagram_id)} · ${new Date(j.created_at).toLocaleString()}</div>
                </div>
                <span style="color:${statusColor};font-weight:600;font-size:12px">${j.status.toUpperCase()}</span>
            </div>`;
        }).join("");
    } catch {}
}

function escapeHtml(str) {
    return String(str ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}

// Load history when Magic page becomes active
document.querySelectorAll(".nav-item").forEach(item => {
    item.addEventListener("click", () => {
        if (item.getAttribute("data-page") === "magic") {
            setTimeout(loadMagicHistory, 300);
        }
    });
});


// ════════════════════════════════════════════════════════════════════════════
//  INSTAGRAM TARGETED FOLLOWERS
// ════════════════════════════════════════════════════════════════════════════

function showTargetResult(elId, data) {
    const el = document.getElementById(elId);
    if (!el) return;
    const mode    = data.mode === "live" ? "🟢 LIVE" : "🟡 SIM";
    const followed = data.followed ?? 0;
    const hashtags = (data.hashtags_used || []).join(", ") || "—";
    const errors   = data.errors?.length ? data.errors.slice(0,3).join("; ") : null;
    el.style.display = "block";
    el.innerHTML = `
      <div style="background:${data.mode==='live'?'#d1fae5':'#eff6ff'};border-radius:10px;padding:14px;font-size:13px">
        <strong>${mode}</strong> — Followed: <strong>${followed}</strong>
        | Skipped (cap): ${data.skipped_daily_cap??0}
        | Already followed: ${data.skipped_already_followed??0}<br>
        <span style="color:#64748b">Hashtags: ${hashtags}</span>
        ${errors ? `<br><span style="color:#ef4444">Errors: ${errors}</span>` : ""}
        ${data.message ? `<br><em style="color:#92400e">${data.message}</em>` : ""}
      </div>`;
}

async function igTargetFollow(type) {
    let payload = {};
    let resultElId = "";
    const btn = event.target;
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Running…';

    if (type === "targeted") {
        payload = {
            gender:        document.getElementById("comb-gender")?.value || null,
            city:          document.getElementById("comb-city")?.value?.trim() || null,
            state:         document.getElementById("comb-state")?.value?.trim() || null,
            business_type: document.getElementById("comb-biz")?.value || null,
            max_follows:   parseInt(document.getElementById("comb-max")?.value ?? "20"),
        };
        resultElId = "ig-tgt-combined-result";
    } else if (type === "gender") {
        payload = {
            gender:      document.getElementById("gender-select")?.value,
            max_follows: parseInt(document.getElementById("gender-max")?.value ?? "20"),
        };
        resultElId = "ig-tgt-gender-result";
    } else if (type === "city") {
        payload = {
            city:        document.getElementById("city-name")?.value?.trim(),
            gender:      document.getElementById("city-gender")?.value || null,
            max_follows: parseInt(document.getElementById("city-max")?.value ?? "20"),
        };
        resultElId = "ig-tgt-city-result";
        if (!payload.city) { showToast("Please enter a city name", "warning"); btn.disabled = false; btn.innerHTML = '<i class="fas fa-map-marker-alt"></i> Follow by City'; return; }
    } else if (type === "state") {
        payload = {
            state:       document.getElementById("state-name")?.value?.trim(),
            city:        document.getElementById("state-city")?.value?.trim() || null,
            gender:      document.getElementById("state-gender")?.value || null,
            max_follows: parseInt(document.getElementById("state-max")?.value ?? "20"),
        };
        resultElId = "ig-tgt-state-result";
        if (!payload.state) { showToast("Please enter a state name", "warning"); btn.disabled = false; btn.innerHTML = '<i class="fas fa-map"></i> Follow by State'; return; }
    } else if (type === "business") {
        payload = {
            business_type: document.getElementById("biz-type")?.value,
            city:          document.getElementById("biz-city")?.value?.trim() || null,
            gender:        document.getElementById("biz-gender")?.value || null,
            max_follows:   parseInt(document.getElementById("biz-max")?.value ?? "20"),
        };
        resultElId = "ig-tgt-business-result";
    }

    // Clean null values
    Object.keys(payload).forEach(k => { if (payload[k] === null || payload[k] === "") delete payload[k]; });

    const endpoint = {
        targeted: "/api/instagram/follow/targeted",
        gender:   "/api/instagram/follow/gender",
        city:     "/api/instagram/follow/city",
        state:    "/api/instagram/follow/state",
        business: "/api/instagram/follow/business",
    }[type];

    try {
        const res = await post(endpoint, payload);
        showTargetResult(resultElId, res);
        showToast(`${res.mode==="live"?"🟢":"🟡"} Followed ${res.followed ?? 0} users`, res.followed > 0 ? "success" : "info");
        await checkInstagramStatus();
    } catch (e) {
        showToast("Failed: " + e.message, "error");
    } finally {
        btn.disabled = false;
        btn.innerHTML = btn.innerHTML.replace(/fa-spinner fa-spin/, "fas fa-user-plus");
        const labels = { targeted:"Start Targeted Follow", gender:"Follow by Gender", city:"Follow by City", state:"Follow by State", business:"Follow by Business" };
        btn.innerHTML = `<i class="fas fa-user-plus"></i> ${labels[type]}`;
    }
}


// ════════════════════════════════════════════════════════════════════════════
//  YOUTUBE MONETIZATION
// ════════════════════════════════════════════════════════════════════════════

async function loadMonetizationReport() {
    try {
        const data = await (await fetch(`${API}/api/youtube/monetization`)).json();
        const whPct  = Math.min(100, data.progress_percent ?? 0);
        const subPct = Math.min(100, data.subscribers_progress_pct ?? 0);

        setText("mon-watch-hours", (data.total_watch_hours ?? 0).toFixed(1));
        setText("mon-progress",    whPct.toFixed(1) + "%");
        setText("mon-remaining",   (data.hours_remaining ?? 4000).toFixed(1));
        setText("mon-subs-today",  data.subscribers_today ?? 0);
        setText("mon-wh-label",    `${(data.total_watch_hours??0).toFixed(1)} / 4,000 hrs`);
        setText("mon-sub-label",   `${data.subscribers_today??0} / 1,000`);
        setText("mon-recommendation", data.recommendation ?? "");

        const whBar  = document.getElementById("mon-wh-bar");
        const subBar = document.getElementById("mon-sub-bar");
        if (whBar)  whBar.style.width  = whPct + "%";
        if (subBar) subBar.style.width = subPct + "%";

        const badge = document.getElementById("yt-mon-mode-badge");
        if (badge) {
            badge.textContent = data.mode === "live" ? "LIVE" : "SIM";
            badge.style.background = data.mode === "live" ? "rgba(16,185,129,.5)" : "rgba(255,255,255,.25)";
        }
    } catch {}
}

async function runWatchTime() {
    const channelId = document.getElementById("wt-channel-id")?.value?.trim();
    const sessions  = parseInt(document.getElementById("wt-sessions")?.value ?? "50");
    if (!channelId) { showToast("Please enter a channel ID", "warning"); return; }

    const btn = event.target; btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Running…';
    try {
        const res = await post("/api/youtube/watch-time", { channel_id: channelId, sessions });
        const el  = document.getElementById("wt-result");
        if (el) {
            el.style.display = "block";
            const mode = res.mode === "live" ? "🔴 LIVE" : "🟡 SIM";
            el.innerHTML = `
              <div style="background:${res.mode==="live"?"#d1fae5":"#eff6ff"};border-radius:10px;padding:14px;font-size:13px">
                <strong>${mode}</strong><br>
                Sessions run: <strong>${res.sessions_run}</strong>
                | Real accounts: <strong>${res.real_accounts_used}</strong>
                | Fake rejected: ${res.fake_rejected}<br>
                Watch hours this run: <strong>${(res.total_watch_hours??0).toFixed(2)}</strong><br>
                Progress: <strong>${(res.progress_percent??0).toFixed(1)}%</strong>
                of 4,000 hrs (${(res.hours_remaining??4000).toFixed(1)} hrs remaining)<br>
                ${res.message ? `<em style="color:#92400e">${res.message}</em>` : ""}
              </div>`;
        }
        showToast(`${res.mode==="live"?"🔴":"🟡"} Watch time: ${(res.total_watch_hours??0).toFixed(2)} hrs (${(res.progress_percent??0).toFixed(1)}%)`, "success");
        await loadMonetizationReport();
    } catch (e) { showToast("Failed: " + e.message, "error"); }
    finally { btn.disabled = false; btn.innerHTML = '<i class="fas fa-play-circle"></i> Accumulate Watch Time'; }
}

async function growRealSubscribers() {
    const query     = document.getElementById("rsub-query")?.value?.trim();
    const maxSubs   = parseInt(document.getElementById("rsub-max")?.value ?? "20");
    const minSubs   = parseInt(document.getElementById("rsub-min-subs")?.value ?? "10");
    const minVideos = parseInt(document.getElementById("rsub-min-videos")?.value ?? "1");
    if (!query) { showToast("Please enter a niche keyword", "warning"); return; }

    const btn = event.target; btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Filtering + Subscribing…';
    try {
        const res = await post("/api/youtube/subscribers/real", {
            query, max_subs: maxSubs,
            min_channel_subs: minSubs, min_channel_videos: minVideos,
        });
        const el = document.getElementById("rsub-result");
        if (el) {
            el.style.display = "block";
            const mode = res.mode === "live" ? "🔴 LIVE" : "🟡 SIM";
            el.innerHTML = `
              <div style="background:${res.mode==="live"?"#d1fae5":"#eff6ff"};border-radius:10px;padding:14px;font-size:13px">
                <strong>${mode}</strong><br>
                Real accounts subscribed: <strong>${res.real_subscribed}</strong><br>
                Bot/fake accounts rejected: <strong>${res.fake_rejected ?? 0}</strong><br>
                ${res.errors?.length ? `<span style="color:#ef4444">Errors: ${res.errors.slice(0,2).join("; ")}</span>` : ""}
                ${res.message ? `<em style="color:#92400e">${res.message}</em>` : ""}
              </div>`;
        }
        showToast(`${res.mode==="live"?"🔴":"🟡"} Real subs: ${res.real_subscribed} | Rejected: ${res.fake_rejected??0}`, "success");
        await loadMonetizationReport();
        await checkYouTubeStatus();
    } catch (e) { showToast("Failed: " + e.message, "error"); }
    finally { btn.disabled = false; btn.innerHTML = '<i class="fas fa-user-check"></i> Grow Real Subscribers'; }
}

// Load monetization report when YT Monetize page opens
document.querySelectorAll(".nav-item").forEach(item => {
    item.addEventListener("click", () => {
        const pg = item.getAttribute("data-page");
        if (pg === "yt-monetize")  setTimeout(loadMonetizationReport, 300);
        if (pg === "ig-targeting") setTimeout(checkInstagramStatus,   300);
    });
});

// Initial load
setTimeout(loadMonetizationReport, 2000);

// ── Engage-back with followers / subscribers (optional) ───────────────────────

async function engageBackFollowers() {
    const comment = document.getElementById("eng-back-comment")?.value?.trim() || "Love this! 🔥";
    const maxE    = parseInt(document.getElementById("eng-back-max")?.value ?? "20");
    const doLike  = document.getElementById("eng-back-like")?.checked ?? true;
    const doCmt   = document.getElementById("eng-back-comment-cb")?.checked ?? false;
    const btn = event.target;
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Engaging…';
    try {
        const res = await post("/api/instagram/engage-followers", {
            comment_text: comment, max_engage: maxE, do_like: doLike, do_comment: doCmt
        });
        const el  = document.getElementById("eng-back-result");
        const mode = res.mode === "live" ? "🟢 LIVE" : "🟡 SIM";
        if (el) {
            el.style.display = "block";
            el.innerHTML = `<div style="background:${res.mode==="live"?"#d1fae5":"#eff6ff"};padding:12px;border-radius:8px;font-size:13px">
                <strong>${mode}</strong> — Liked: <strong>${res.liked}</strong> | Commented: <strong>${res.commented}</strong> | Skipped: ${res.skipped ?? 0}
                ${res.message ? "<br><em style='color:#92400e'>" + escapeHtml(res.message) + "</em>" : ""}
            </div>`;
        }
        showToast(`${mode} Liked: ${res.liked} | Commented: ${res.commented}`, "success");
        await checkInstagramStatus();
    } catch(e) { showToast("Failed: " + e.message, "error"); }
    finally { btn.disabled = false; btn.innerHTML = '<i class="fas fa-hand-holding-heart"></i> Engage with Followers'; }
}

async function engageWithSubscribers() {
    const comment = document.getElementById("sub-eng-comment")?.value?.trim() || "Great content! 🔥";
    const maxE    = parseInt(document.getElementById("sub-eng-max")?.value ?? "10");
    const doLike  = document.getElementById("sub-eng-like")?.checked ?? true;
    const doCmt   = document.getElementById("sub-eng-comment-cb")?.checked ?? false;
    const btn = event.target;
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Engaging…';
    try {
        const res = await post("/api/youtube/engage-subscribers", {
            comment_text: comment, max_engage: maxE, do_like: doLike, do_comment: doCmt
        });
        const el   = document.getElementById("sub-eng-result");
        const mode = res.mode === "live" ? "🔴 LIVE" : "🟡 SIM";
        if (el) {
            el.style.display = "block";
            el.innerHTML = `<div style="background:${res.mode==="live"?"#d1fae5":"#eff6ff"};padding:12px;border-radius:8px;font-size:13px">
                <strong>${mode}</strong> — Liked: <strong>${res.liked}</strong> | Commented: <strong>${res.commented}</strong> | Skipped: ${res.skipped ?? 0}
                ${res.message ? "<br><em style='color:#92400e'>" + escapeHtml(res.message) + "</em>" : ""}
            </div>`;
        }
        showToast(`${mode} Liked: ${res.liked} | Commented: ${res.commented}`, "success");
        await loadMonetizationReport();
    } catch(e) { showToast("Failed: " + e.message, "error"); }
    finally { btn.disabled = false; btn.innerHTML = '<i class="fas fa-hand-holding-heart"></i> Engage with Subscribers'; }
}


// ── Engage-back with followers / subscribers (optional action) ────────────────

async function engageBackFollowers() {
    const comment = document.getElementById("eng-back-comment")?.value?.trim() || "Love this! 🔥";
    const maxE    = parseInt(document.getElementById("eng-back-max")?.value ?? "20");
    const doLike  = document.getElementById("eng-back-like")?.checked ?? true;
    const doCmt   = document.getElementById("eng-back-comment-cb")?.checked ?? false;
    const btn = event.target;
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Engaging…';
    try {
        const res = await post("/api/instagram/engage-followers", {
            comment_text: comment, max_engage: maxE, do_like: doLike, do_comment: doCmt
        });
        const el   = document.getElementById("eng-back-result");
        const mode = res.mode === "live" ? "🟢 LIVE" : "🟡 SIM";
        if (el) {
            el.style.display = "block";
            el.innerHTML = `<div style="background:${res.mode==="live"?"#d1fae5":"#eff6ff"};padding:12px;border-radius:8px;font-size:13px">
                <strong>${mode}</strong> — Liked: <strong>${res.liked}</strong> | Commented: <strong>${res.commented}</strong> | Skipped: ${res.skipped ?? 0}
                ${res.message ? "<br><em style='color:#92400e'>"+escapeHtml(res.message)+"</em>" : ""}
            </div>`;
        }
        showToast(`${mode} Liked: ${res.liked} | Commented: ${res.commented}`, "success");
        await checkInstagramStatus();
    } catch(e) { showToast("Failed: " + e.message, "error"); }
    finally { btn.disabled = false; btn.innerHTML = '<i class="fas fa-hand-holding-heart"></i> Engage with Followers'; }
}

async function engageWithSubscribers() {
    const comment = document.getElementById("sub-eng-comment")?.value?.trim() || "Great content! 🔥";
    const maxE    = parseInt(document.getElementById("sub-eng-max")?.value ?? "10");
    const doLike  = document.getElementById("sub-eng-like")?.checked ?? true;
    const doCmt   = document.getElementById("sub-eng-comment-cb")?.checked ?? false;
    const btn = event.target;
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Engaging…';
    try {
        const res = await post("/api/youtube/engage-subscribers", {
            comment_text: comment, max_engage: maxE, do_like: doLike, do_comment: doCmt
        });
        const el   = document.getElementById("sub-eng-result");
        const mode = res.mode === "live" ? "🔴 LIVE" : "🟡 SIM";
        if (el) {
            el.style.display = "block";
            el.innerHTML = `<div style="background:${res.mode==="live"?"#d1fae5":"#eff6ff"};padding:12px;border-radius:8px;font-size:13px">
                <strong>${mode}</strong> — Liked: <strong>${res.liked}</strong> | Commented: <strong>${res.commented}</strong> | Skipped: ${res.skipped ?? 0}
                ${res.message ? "<br><em style='color:#92400e'>"+escapeHtml(res.message)+"</em>" : ""}
            </div>`;
        }
        showToast(`${mode} Liked: ${res.liked} | Commented: ${res.commented}`, "success");
        await loadMonetizationReport();
    } catch(e) { showToast("Failed: " + e.message, "error"); }
    finally { btn.disabled = false; btn.innerHTML = '<i class="fas fa-hand-holding-heart"></i> Engage with Subscribers'; }
}


// ════════════════════════════════════════════════════════════════════════════
//  SETUP WIZARD — One-Click OAuth + Manual fallback
// ════════════════════════════════════════════════════════════════════════════

// ── Wizard step activation helpers ───────────────────────────────────────────

function activateStep(stepId) {
    const el = document.getElementById(stepId);
    if (el) { el.classList.remove("blocked"); el.classList.add("active"); }
}
function markStepDone(stepId) {
    const el = document.getElementById(stepId);
    if (el) { el.classList.remove("active"); el.classList.add("done"); }
}

// ── Instagram wizard ──────────────────────────────────────────────────────────

function toggleIGStep2() {
    markStepDone("ig-step-1");
    activateStep("ig-step-2");
    document.getElementById("ig-step-2")?.scrollIntoView({ behavior: "smooth", block: "center" });
}

function activateIGConnect() {
    const appId     = document.getElementById("ig-app-id")?.value?.trim();
    const appSecret = document.getElementById("ig-app-secret")?.value?.trim();
    if (!appId || !appSecret) {
        showToast("Please enter your App ID and App Secret", "warning");
        return;
    }
    markStepDone("ig-step-2");
    activateStep("ig-step-3");
    document.getElementById("ig-step-3")?.scrollIntoView({ behavior: "smooth", block: "center" });
}

async function connectInstagram() {
    const appId     = document.getElementById("ig-app-id")?.value?.trim();
    const appSecret = document.getElementById("ig-app-secret")?.value?.trim();
    if (!appId || !appSecret) {
        showToast("Please complete Steps 1 and 2 first", "warning");
        return;
    }

    const btn = document.getElementById("ig-connect-btn");
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Opening login window...';

    try {
        // Get the auth URL from the backend
        const res = await post("/api/oauth/instagram/start", {
            app_id:     appId,
            app_secret: appSecret,
        });

        const authUrl = res.auth_url;

        // Open popup centered on screen
        const w = 600, h = 700;
        const left = Math.round(screen.width  / 2 - w / 2);
        const top  = Math.round(screen.height / 2 - h / 2);
        const popup = window.open(authUrl, "ig_oauth",
            `width=${w},height=${h},left=${left},top=${top},scrollbars=yes`);

        const statusEl = document.getElementById("ig-connect-status");

        if (statusEl) {
            statusEl.style.display = "block";
            statusEl.innerHTML = `<div style="background:#eff6ff;padding:12px;border-radius:8px;font-size:13px">
                <i class="fas fa-info-circle" style="color:#3b82f6"></i>
                Login popup opened. Approve access in the new window...
            </div>`;
        }

        // Listen for postMessage from the popup
        window.addEventListener("message", async function handler(e) {
            if (e.data?.type === "oauth_success" && e.data?.platform === "instagram") {
                window.removeEventListener("message", handler);
                popup?.close();
                markStepDone("ig-step-3");

                if (statusEl) {
                    statusEl.innerHTML = `<div style="background:#d1fae5;padding:12px;border-radius:8px;font-size:13px;color:#065f46">
                        <strong><i class="fas fa-check-circle"></i> Instagram Connected!</strong><br>
                        Live mode is now active. You can start growing followers.
                    </div>`;
                }

                // Update status cards
                await updateConnectionStatus();
                showToast("Instagram connected! Live mode active.", "success");
                btn.innerHTML = '<i class="fab fa-instagram"></i> Connected ✓';
                btn.style.background = "#10b981";
            }
            if (e.data?.type === "oauth_error" && e.data?.platform === "instagram") {
                window.removeEventListener("message", handler);
                popup?.close();
                showToast("Instagram connection failed: " + e.data.error, "error");
                btn.disabled = false;
                btn.innerHTML = '<i class="fab fa-instagram"></i> Connect Instagram — One Click';
            }
        });

        // Check if popup was blocked
        if (!popup || popup.closed) {
            showToast("Popup blocked! Please allow popups for this site, then try again.", "error");
            btn.disabled = false;
            btn.innerHTML = '<i class="fab fa-instagram"></i> Connect Instagram — One Click';
        }

    } catch (e) {
        showToast("Failed to start OAuth: " + e.message, "error");
        btn.disabled = false;
        btn.innerHTML = '<i class="fab fa-instagram"></i> Connect Instagram — One Click';
    }
}

// ── YouTube wizard ────────────────────────────────────────────────────────────

function toggleYTStep2() {
    markStepDone("yt-step-1");
    activateStep("yt-step-2");
    document.getElementById("yt-step-2")?.scrollIntoView({ behavior: "smooth", block: "center" });
}

function activateYTConnect() {
    const cid = document.getElementById("yt-oauth-client-id")?.value?.trim();
    const cs  = document.getElementById("yt-oauth-client-secret")?.value?.trim();
    if (!cid || !cs) {
        showToast("Please enter your Client ID and Client Secret", "warning");
        return;
    }
    markStepDone("yt-step-2");
    activateStep("yt-step-3");
    document.getElementById("yt-step-3")?.scrollIntoView({ behavior: "smooth", block: "center" });
}

async function connectYouTube() {
    const clientId     = document.getElementById("yt-oauth-client-id")?.value?.trim();
    const clientSecret = document.getElementById("yt-oauth-client-secret")?.value?.trim();
    if (!clientId || !clientSecret) {
        showToast("Please complete Steps 1 and 2 first", "warning");
        return;
    }

    const btn = document.getElementById("yt-connect-btn");
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Opening Google login...';

    try {
        const res = await post("/api/oauth/youtube/start", {
            client_id:     clientId,
            client_secret: clientSecret,
        });

        const authUrl = res.auth_url;
        const w = 500, h = 650;
        const left = Math.round(screen.width  / 2 - w / 2);
        const top  = Math.round(screen.height / 2 - h / 2);
        const popup = window.open(authUrl, "yt_oauth",
            `width=${w},height=${h},left=${left},top=${top},scrollbars=yes`);

        const statusEl = document.getElementById("yt-connect-status");
        if (statusEl) {
            statusEl.style.display = "block";
            statusEl.innerHTML = `<div style="background:#eff6ff;padding:12px;border-radius:8px;font-size:13px">
                <i class="fas fa-info-circle" style="color:#3b82f6"></i>
                Google login popup opened. Select your account and approve access...
            </div>`;
        }

        window.addEventListener("message", async function handler(e) {
            if (e.data?.type === "oauth_success" && e.data?.platform === "youtube") {
                window.removeEventListener("message", handler);
                popup?.close();
                markStepDone("yt-step-3");

                if (statusEl) {
                    statusEl.innerHTML = `<div style="background:#d1fae5;padding:12px;border-radius:8px;font-size:13px;color:#065f46">
                        <strong><i class="fas fa-check-circle"></i> YouTube Connected!</strong><br>
                        Refresh token saved. Live mode is now active. Watch time tracking enabled.
                    </div>`;
                }

                await updateConnectionStatus();
                showToast("YouTube connected! Live mode active.", "success");
                btn.innerHTML = '<i class="fab fa-youtube"></i> Connected ✓';
                btn.style.background = "#10b981";
            }
            if (e.data?.type === "oauth_error" && e.data?.platform === "youtube") {
                window.removeEventListener("message", handler);
                popup?.close();
                showToast("YouTube connection failed: " + e.data.error, "error");
                btn.disabled = false;
                btn.innerHTML = '<i class="fab fa-youtube"></i> Connect YouTube — One Click';
            }
        });

        if (!popup || popup.closed) {
            showToast("Popup blocked! Please allow popups for this site, then try again.", "error");
            btn.disabled = false;
            btn.innerHTML = '<i class="fab fa-youtube"></i> Connect YouTube — One Click';
        }

    } catch (e) {
        showToast("Failed to start OAuth: " + e.message, "error");
        btn.disabled = false;
        btn.innerHTML = '<i class="fab fa-youtube"></i> Connect YouTube — One Click';
    }
}

// ── Status card updater ───────────────────────────────────────────────────────

async function updateConnectionStatus() {
    try {
        const ig = await (await fetch(`${API}/api/instagram/status`)).json();
        const yt = await (await fetch(`${API}/api/youtube/status`)).json();

        // IG pill
        const igPill = document.getElementById("ig-connection-pill");
        const igDetail = document.getElementById("ig-connection-detail");
        if (igPill) {
            igPill.textContent = ig.configured ? "LIVE" : "SIM";
            igPill.className   = "status-pill " + (ig.configured ? "pill-live" : "pill-sim");
        }
        if (igDetail) {
            igDetail.textContent = ig.configured
                ? "Connected · User ID: " + (ig.user_id || "—") + " · Follows left: " + (ig.daily_stats?.follows_remaining ?? "—")
                : "Not connected — configure below";
        }

        // YT pill
        const ytPill = document.getElementById("yt-connection-pill");
        const ytDetail = document.getElementById("yt-connection-detail");
        if (ytPill) {
            ytPill.textContent = yt.configured ? "LIVE" : "SIM";
            ytPill.className   = "status-pill " + (yt.configured ? "pill-live" : "pill-sim");
        }
        if (ytDetail) {
            ytDetail.textContent = yt.configured
                ? "Connected · Quota: " + (yt.daily_stats?.quota_used ?? 0) + " / 10,000 units used today"
                : "Not connected — configure below";
        }

        // Also sync the mode badges on other pages
        const igModeBadge = document.getElementById("ig-mode-badge");
        const igTgtBadge  = document.getElementById("ig-tgt-mode-badge");
        const ytModeBadge = document.getElementById("yt-mode-badge");
        const ytMonBadge  = document.getElementById("yt-mon-mode-badge");

        if (igModeBadge) { igModeBadge.textContent = ig.configured ? "LIVE" : "SIM"; igModeBadge.style.background = ig.configured ? "var(--success)" : "var(--warning)"; }
        if (igTgtBadge)  { igTgtBadge.textContent  = ig.configured ? "LIVE" : "SIM"; igTgtBadge.style.background  = ig.configured ? "var(--success)" : "var(--warning)"; }
        if (ytModeBadge) { ytModeBadge.textContent = yt.configured ? "LIVE" : "SIM"; ytModeBadge.style.background = yt.configured ? "var(--success)" : "var(--warning)"; }
        if (ytMonBadge)  { ytMonBadge.textContent  = yt.configured ? "LIVE" : "SIM"; ytMonBadge.style.background  = yt.configured ? "var(--success)" : "var(--warning)"; }

    } catch {}
}

// ── Manual fallback ───────────────────────────────────────────────────────────

async function manualSaveIG() {
    const token = document.getElementById("man-ig-token")?.value?.trim();
    const uid   = document.getElementById("man-ig-uid")?.value?.trim();
    if (!token || !uid) { showToast("Please fill in both fields", "warning"); return; }
    try {
        await post("/api/instagram/credentials", { instagram_access_token: token, instagram_user_id: uid });
        showToast("Instagram credentials saved!", "success");
        await updateConnectionStatus();
    } catch(e) { showToast("Failed: " + e.message, "error"); }
}

async function manualSaveYT() {
    const cid  = document.getElementById("man-yt-cid")?.value?.trim();
    const csec = document.getElementById("man-yt-csec")?.value?.trim();
    const ref  = document.getElementById("man-yt-ref")?.value?.trim();
    if (!cid || !csec || !ref) { showToast("Please fill in all three fields", "warning"); return; }
    try {
        await post("/api/youtube/credentials", { client_id: cid, client_secret: csec, refresh_token: ref, channel_id: "" });
        showToast("YouTube credentials saved!", "success");
        await updateConnectionStatus();
    } catch(e) { showToast("Failed: " + e.message, "error"); }
}

// Auto-load status when setup page opens
document.querySelectorAll(".nav-item").forEach(item => {
    item.addEventListener("click", () => {
        if (item.getAttribute("data-page") === "setup") {
            setTimeout(updateConnectionStatus, 300);
        }
    });
});

// Initial status check
setTimeout(updateConnectionStatus, 2500);


// ════════════════════════════════════════════════════════════════════════════
//  AUTH GUARD  —  Token management, route protection, user session
// ════════════════════════════════════════════════════════════════════════════

const TOKEN_KEY   = "bp_access";
const REFRESH_KEY = "bp_refresh";
const USER_KEY    = "bp_user";

// ── Token helpers ─────────────────────────────────────────────────────────────

function getAccessToken() {
    return localStorage.getItem(TOKEN_KEY) || sessionStorage.getItem(TOKEN_KEY) || "";
}
function getRefreshToken() {
    return localStorage.getItem(REFRESH_KEY) || sessionStorage.getItem(REFRESH_KEY) || "";
}
function getStoredUser() {
    try {
        const raw = localStorage.getItem(USER_KEY) || sessionStorage.getItem(USER_KEY);
        return raw ? JSON.parse(raw) : null;
    } catch { return null; }
}
function clearSession() {
    [localStorage, sessionStorage].forEach(s => {
        s.removeItem(TOKEN_KEY);
        s.removeItem(REFRESH_KEY);
        s.removeItem(USER_KEY);
    });
}

// ── Authenticated fetch wrapper (auto-refresh on 401) ─────────────────────────

async function authFetch(url, options = {}) {
    const token = getAccessToken();
    options.headers = { ...(options.headers || {}), "Authorization": "Bearer " + token };

    let res = await fetch(url, options);

    if (res.status === 401) {
        // Try refreshing the access token
        const refreshToken = getRefreshToken();
        if (!refreshToken) {
            redirectToLogin();
            throw new Error("Session expired");
        }
        const rr = await fetch(`${API}/api/auth/refresh`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ refresh_token: refreshToken }),
        });
        if (!rr.ok) {
            clearSession();
            redirectToLogin();
            throw new Error("Session expired — please log in again");
        }
        const refreshData = await rr.json();
        // Save new access token (preserve storage type)
        const store = localStorage.getItem(TOKEN_KEY) ? localStorage : sessionStorage;
        store.setItem(TOKEN_KEY, refreshData.access_token);

        // Retry original request with new token
        options.headers["Authorization"] = "Bearer " + refreshData.access_token;
        res = await fetch(url, options);
    }
    return res;
}

// Override the existing `post` helper to use authFetch
async function post(path, body) {
    const res = await authFetch(`${API}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
    if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
    }
    return res.json();
}

// ── Route guard ───────────────────────────────────────────────────────────────

function redirectToLogin() {
    window.location.href = "auth.html";
}

async function checkAuthGuard() {
    const token = getAccessToken();
    if (!token) {
        redirectToLogin();
        return;
    }
    // Validate token against /api/auth/me
    try {
        const res = await fetch(`${API}/api/auth/me`, {
            headers: { "Authorization": "Bearer " + token }
        });
        if (res.status === 401) {
            // Try refresh
            const refresh = getRefreshToken();
            if (!refresh) { clearSession(); redirectToLogin(); return; }
            const rr = await fetch(`${API}/api/auth/refresh`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ refresh_token: refresh }),
            });
            if (!rr.ok) { clearSession(); redirectToLogin(); return; }
            const rd = await rr.json();
            const store = localStorage.getItem(TOKEN_KEY) ? localStorage : sessionStorage;
            store.setItem(TOKEN_KEY, rd.access_token);
            // Load user again
            const r2 = await fetch(`${API}/api/auth/me`, {
                headers: { "Authorization": "Bearer " + rd.access_token }
            });
            if (!r2.ok) { clearSession(); redirectToLogin(); return; }
            const d2 = await r2.json();
            updateSidebarUser(d2.user);
        } else if (!res.ok) {
            clearSession(); redirectToLogin(); return;
        } else {
            const data = await res.json();
            updateSidebarUser(data.user);
        }
    } catch {
        // API offline — allow cached user
        const cached = getStoredUser();
        if (!cached) { redirectToLogin(); return; }
        updateSidebarUser(cached);
    }
}

function updateSidebarUser(user) {
    if (!user) return;
    const unEl   = document.getElementById("sidebar-username");
    const roleEl = document.getElementById("sidebar-role");
    if (unEl)   unEl.textContent   = user.full_name || user.username;
    if (roleEl) roleEl.textContent = user.is_admin ? "Administrator" : "Bot Operator";
}

// ── Logout ────────────────────────────────────────────────────────────────────

async function logoutCurrent() {
    if (!confirm("Sign out of this device?")) return;
    const refreshToken = getRefreshToken();
    try {
        const token = getAccessToken();
        await fetch(`${API}/api/auth/logout`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": "Bearer " + token,
            },
            body: JSON.stringify({ refresh_token: refreshToken, logout_all: false }),
        });
    } catch {}
    clearSession();
    showToast("Signed out successfully", "info");
    setTimeout(() => redirectToLogin(), 800);
}

async function logoutAll() {
    if (!confirm("Sign out of ALL devices? All active sessions will be terminated.")) return;
    const refreshToken = getRefreshToken();
    try {
        const token = getAccessToken();
        await fetch(`${API}/api/auth/logout`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": "Bearer " + token,
            },
            body: JSON.stringify({ refresh_token: refreshToken, logout_all: true }),
        });
    } catch {}
    clearSession();
    showToast("Signed out from all devices", "info");
    setTimeout(() => redirectToLogin(), 800);
}

// ── Wire the old logout button in case it still exists ────────────────────────
document.querySelector(".logout-btn")?.addEventListener("click", function(e) {
    // The new buttons use onclick= directly; this handles any legacy button
    if (!e.target.closest("[onclick]")) {
        logoutCurrent();
    }
});

// ── Add auth headers to all future API calls ─────────────────────────────────
const _origFetch = window.fetch.bind(window);
window.fetch = function(url, opts = {}) {
    // Only inject auth header for our API calls
    if (typeof url === "string" && url.startsWith(API + "/api/") &&
        !url.includes("/api/auth/login") &&
        !url.includes("/api/auth/register") &&
        !url.includes("/api/auth/refresh")) {
        const token = getAccessToken();
        if (token) {
            opts.headers = { ...(opts.headers || {}), "Authorization": "Bearer " + token };
        }
    }
    return _origFetch(url, opts);
};

// ── Boot: run auth guard as soon as DOM is ready ──────────────────────────────
document.addEventListener("DOMContentLoaded", function() {
    checkAuthGuard();
});
