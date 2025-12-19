import React, { useEffect, useState, useRef } from "react";
import Sidebar from "./Sidebar";
import "./Dashboard.css";
import useAuth from "../hooks/useAuth";
import { logout } from "../firebase";
import { listenUserHistory, saveSessionForUser, getSession, updateSession, deleteSession } from "../firestore";
import { auth } from "../firebase";
import { useNavigate } from "react-router-dom";

const BACKEND_URL = "http://127.0.0.1:5001";

export default function Dashboard() {
  const { user, loading: authLoading } = useAuth();
  const nav = useNavigate();

  
  const [collapsed, setCollapsed] = useState(false);
  const [sessions, setSessions] = useState([]);
  const [current, setCurrent] = useState(null); // structure described below
  const [urlsText, setUrlsText] = useState("");
  const [loadingTranscripts, setLoadingTranscripts] = useState(false);
  const [importedCount, setImportedCount] = useState(null);

  
  const [analyzingState, setAnalyzingState] = useState(null);

  // throughput test state
  const [throughputResults, setThroughputResults] = useState(null);
  const [runningThroughputTest, setRunningThroughputTest] = useState(false);

  // Admin check
  const ADMIN_EMAILS = ['seanhealy0210@gmail.com']; 
  const isAdmin = user && ADMIN_EMAILS.includes(user.email);

  // local refs
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  // subscribe to user history
  useEffect(() => {
    if (!user) {
      // load local sessions from localStorage for unauthenticated users
      try {
        const raw = window.localStorage.getItem('local_sessions');
        const local = raw ? JSON.parse(raw) : [];
        setSessions(local);
      } catch (e) {
        console.warn('Failed to load local sessions', e);
        setSessions([]);
      }
      return;
    }
    const unsub = listenUserHistory(user.uid, async (items) => {
      console.log('listenUserHistory: received items count', items.length, items.map(it => ({ id: it.id, title: it.title })));
      setSessions(items);

      // If no current or current is null, pick newest item
      setCurrent((prev) => {
        if (!prev && items.length) {
          // make sure current matches the shape used by this component
          const first = items[0];
          // If Firestore saved sessions follow { title, urls, transcript, analysis, videos? } shape,
          // try to use videos array if present, otherwise create videos from transcript field.
          if (first.videos && Array.isArray(first.videos)) {
            return { ...first };
          } else {
            // attempt to split saved transcript into single video entry
            return {
              ...first,
              videos: [{
                url: first.urls?.[0] || "",
                title: first.title || "Untitled session",
                transcript: first.transcript || "",
                analysis: first.analysis || ""
              }]
            };
          }
        }
        return prev;
      });

      // If listener reports zero items, attempt a one-time fetch to verify existence in Firestore
      if ((!items || items.length === 0) && user) {
        try {
          const { fetchUserHistoryOnce } = await import('../firestore');
          const once = await fetchUserHistoryOnce(user.uid);
          console.log('listenUserHistory: one-time fetch returned', once.length, once.map(i=>({id:i.id, title:i.title})));
          if (once && once.length) setSessions(once);
        } catch (e) {
          console.warn('listenUserHistory: one-time fetch failed', e);
        }
      }
    });
    return () => unsub();
  }, [user]);

  const toggle = () => setCollapsed((c) => !c);

  const onLogout = async () => {
    await logout();
    nav("/login");
  };

  // Create a blank "new session" main panel
  const onNew = () => {
    setCurrent({
      id: null,
      title: "Untitled session",
      urls: [],
      videos: [],  
      createdAt: null,
    });
    setUrlsText("");
  };

  const onSelect = async (s) => {
    // s is a session object from Firestore
    if (!s) return;
    // ensure we have `videos` array
    if (s.videos && Array.isArray(s.videos)) {
      setCurrent({ ...s });
    } else {
      // fallback construct videos from stored transcript (single)
      setCurrent({
        ...s,
        videos: [{
          url: s.urls?.[0] || "",
          title: s.title || "Untitled session",
          transcript: s.transcript || "",
          analysis: s.analysis || ""
        }]
      });
    }
  };

  // Helper: saves the current session to Firestore and updates current.id
  const persistCurrentSession = async (sessionObj) => {
    const toSave = {
      title: sessionObj.title || "Untitled session",
      urls: sessionObj.urls || [],
      videos: sessionObj.videos ?? [],
      transcript: sessionObj.videos && sessionObj.videos.length ? sessionObj.videos.map(v => v.transcript).join("\n\n") : sessionObj.transcript || "",
      analysis: sessionObj.videos && sessionObj.videos.length ? sessionObj.videos.map(v => v.analysis).join("\n\n") : sessionObj.analysis || "",
      createdAt: new Date()
    };

    if (!user) {
      // fallback: save to localStorage for unauthenticated users
      try {
        const raw = window.localStorage.getItem('local_sessions');
        const local = raw ? JSON.parse(raw) : [];
        // If this is an existing local session, update it instead of creating a new one
        if (sessionObj.id && sessionObj.id.startsWith('local-')) {
          const updated = local.map((it) => it.id === sessionObj.id ? ({ ...it, ...toSave, id: it.id }) : it);
          window.localStorage.setItem('local_sessions', JSON.stringify(updated));
          const found = updated.find(it => it.id === sessionObj.id);
          setCurrent(found);
          setSessions(updated);
          console.log('persistCurrentSession: updated local session', sessionObj.id);
          return sessionObj.id;
        }

        const localId = sessionObj.id || `local-${Date.now()}`;
        const item = { id: localId, ...toSave };
        const filtered = local.filter((it) => it.id !== item.id);
        filtered.unshift(item);
        window.localStorage.setItem('local_sessions', JSON.stringify(filtered));
        setCurrent(item);
        setSessions(filtered);
        console.log('persistCurrentSession: saved locally', localId);
        return localId;
      } catch (e) {
        console.error('persistCurrentSession: failed to save locally', e);
        throw e;
      }
    }

    try {
      console.log('persistCurrentSession: saving to firestore for uid', user.uid);
      // If sessionObj has an id, existing document is updated rather than creating a new one
      if (sessionObj.id) {
        try {
          await updateSession(user.uid, sessionObj.id, toSave);
          const item = { ...toSave, id: sessionObj.id, createdAt: new Date() };
          setCurrent(item);
          // update sessions array (replace existing by id)
          setSessions((prev) => {
            const existing = prev || [];
            const filtered = existing.filter(s => s.id !== item.id);
            return [item, ...filtered];
          });
          console.log('persistCurrentSession: updated firestore doc', sessionObj.id);
          return sessionObj.id;
        } catch (uerr) {
          console.warn('persistCurrentSession: update failed, falling back to create', uerr);
          // fallthrough to create
        }
      }

      const id = await saveSessionForUser(user.uid, toSave);
      // update local current with id
      const item = { ...toSave, id, createdAt: new Date() };
      setCurrent(item);
      // optimistically update sessions state so sidebar shows immediately (dedupe by id)
      setSessions((prev) => {
        const existing = prev || [];
        const filtered = existing.filter(s => s.id !== item.id);
        return [item, ...filtered];
      });
      console.log('persistCurrentSession: saved to firestore', id);

      // verify by reading the saved document back from Firestore
      try {
        const saved = await getSession(user.uid, id);
        console.log('persistCurrentSession: verified saved session from firestore', saved);
      } catch (readErr) {
        console.warn('persistCurrentSession: could not read back saved session', readErr);
      }

      return id;
    } catch (e) {
      console.error('persistCurrentSession: firestore save failed', e);
      // as a fallback, save locally so user doesn't lose work
      try {
        const raw = window.localStorage.getItem('local_sessions');
        const local = raw ? JSON.parse(raw) : [];
        const localId = `local-${Date.now()}`;
        const item = { id: localId, ...toSave };
        local.unshift(item);
        window.localStorage.setItem('local_sessions', JSON.stringify(local));
        setCurrent(item);
        setSessions(local);
        console.warn('persistCurrentSession: saved locally after firestore failure', localId);
        return localId;
      } catch (e2) {
        console.error('persistCurrentSession: failed both firestore and local save', e2);
        throw e2;
      }
    }
  };

  // Delete a session 
  const handleDeleteSession = async (s) => {
    if (!s) return;
    const ok = window.confirm(`Delete session "${s.title || 'Untitled'}"? This cannot be undone.`);
    if (!ok) return;

    if (!user) {
      try {
        const raw = window.localStorage.getItem('local_sessions');
        const local = raw ? JSON.parse(raw) : [];
        const filtered = local.filter(it => it.id !== s.id);
        window.localStorage.setItem('local_sessions', JSON.stringify(filtered));
        setSessions(filtered);
        if (current && current.id === s.id) setCurrent(null);
      } catch (e) {
        console.error('handleDeleteSession: failed to delete local session', e);
        alert('Delete failed');
      }
      return;
    }

    try {
      await deleteSession(user.uid, s.id);
      // remove from local sessions state (listener may update too)
      setSessions(prev => (prev || []).filter(it => it.id !== s.id));
      if (current && current.id === s.id) setCurrent(null);
      console.log('handleDeleteSession: deleted', s.id);
    } catch (e) {
      console.error('handleDeleteSession: delete failed', e);
      alert('Delete failed: ' + e.message);
    }
  };

  // Extract YouTube id is handled server-side; here we send URLs to /transcripts
  // Helper: sanitize YouTube URLs to remove playlist params (send single-video URLs)
  const sanitizeYoutubeUrl = (u) => {
    try {
      const url = new URL(u);
      if (url.hostname.includes('youtu.be')) {
        const id = url.pathname.slice(1);
        if (id) return `https://www.youtube.com/watch?v=${id}`;
      }
      // If it's a playlist link, preserve as a canonical playlist URL so server can expand it
      if (url.hostname.includes('youtube.com')) {
        const listId = url.searchParams.get('list');
        if (listId) return `https://www.youtube.com/playlist?list=${listId}`;
        const v = url.searchParams.get('v');
        if (v) return `https://www.youtube.com/watch?v=${v}`;
        const parts = url.pathname.split('/');
        const embedIdx = parts.indexOf('embed');
        if (embedIdx !== -1 && parts[embedIdx + 1]) return `https://www.youtube.com/watch?v=${parts[embedIdx + 1]}`;
      }
      return u; // fallback to original
    } catch (e) {
      return u;
    }
  };
  const PLAYLIST_WARNING_THRESHOLD = 10;

  const fetchTranscripts = async () => {
    const urlList = urlsText
      .split("\n")
      .map((u) => u.trim())
      .filter(Boolean);

    if (urlList.length === 0) {
      alert("Enter at least one URL");
      return;
    }

    setLoadingTranscripts(true);

    try {
      // sanitize URLs to avoid sending playlist params which the backend may not expand reliably
      const sanitized = urlList.map(sanitizeYoutubeUrl);
      // If any sanitized url is a playlist, warn the user (playlists can be large)
      const containsPlaylist = sanitized.some(u => u.includes('/playlist?list=') || u.includes('list='));
      if (containsPlaylist) {
        const ok = window.confirm("One or more inputs look like a playlist. Playlists can contain many videos and take a long time to process. Continue?");
        if (!ok) {
          return;
        }
      }

      console.log("fetchTranscripts: sending request", { BACKEND_URL, urlList, sanitized });
      setImportedCount(null);
      // attach Firebase ID token if available
      let token = null;
      try {
        token = auth.currentUser ? await auth.currentUser.getIdToken() : null;
      } catch (e) {
        console.warn('Could not get id token', e);
      }
      const headers = { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) };
      const res = await fetch(`${BACKEND_URL}/transcripts`, {
        method: "POST",
        headers,
        body: JSON.stringify({ urls: sanitized }),
      });
      console.log("fetchTranscripts: response status", res.status);
      const data = await res.json();
      console.log("fetchTranscripts: response data", data);
      if (!res.ok) {
        console.error("fetchTranscripts: server returned error", { status: res.status, data });
        throw new Error(data.error || `Server responded ${res.status}`);
      }

      // Build videos array: preserve title if present, transcript if present
      const resultsArr = Array.isArray(data) ? data : data.results;
      const videos = resultsArr.map((d, i) => ({
        url: d.url || urlList[i] || "",
        title: d.title || `Video ${i + 1}`,
        transcript: d.transcript || "",
        analysis: ""
      }));

      const session = {
        id: null,
        title: videos[0]?.title || "Untitled session",
        urls: urlList,
        videos,
        createdAt: null
      };

      setCurrent(session);
      console.log('fetchTranscripts: built session', { videosCount: videos.length, firstTranscriptPreview: videos[0]?.transcript?.slice(0,160) });
      setImportedCount(videos.length || 0);

      // Auto-save fetched session for authenticated users so it persists on refresh
      try {
        if (user) {
          const savedId = await persistCurrentSession(session);
          // update current with the new id
          setCurrent((prev) => ({ ...(prev || session), id: savedId }));
        }
      } catch (err) {
        console.warn("Auto-save after fetch failed:", err);
      }
    } catch (e) {
      console.error(e);
      alert("Failed to fetch one or more transcripts. See console.");
    } finally {
      if (mountedRef.current) setLoadingTranscripts(false);
    }
  };

  // Analyze a single video (per-video analysis)
  const analyzeVideo = async (videoIndex) => {
    if (!current || !current.videos || !current.videos[videoIndex]) {
      alert("No video to analyze");
      return;
    }
    const video = current.videos[videoIndex];
    if (!video.transcript || video.transcript.trim().length === 0) {
      alert("Video has no transcript to analyze");
      return;
    }

    // set state to analyzing this index
    setAnalyzingState({ type: "single", idx: videoIndex });

    try {
      // attach id token if present
      let token = null;
      try {
        token = auth.currentUser ? await auth.currentUser.getIdToken() : null;
      } catch (e) {
        console.warn('Could not get id token', e);
      }
      const analyzeHeaders = { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) };
      const res = await fetch(`${BACKEND_URL}/analyze`, {
        method: "POST",
        headers: analyzeHeaders,
        // ask backend to analyze this single transcript
        body: JSON.stringify({ transcript: video.transcript }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Analysis failed");

      const finalAnalysis = data.final_analysis || data.analysis || (data.partial_summaries && data.partial_summaries.join("\n\n")) || "No analysis returned";

      // update current.videos[videoIndex].analysis
      setCurrent((prev) => {
        const copy = { ...prev, videos: prev.videos.map((v, i) => i === videoIndex ? { ...v, analysis: finalAnalysis } : v) };
        return copy;
      });

      // persist session (save after each analysis so history shows incremental work)
      try {
        await persistCurrentSession({ ...current, videos: current.videos.map((v, i) => i === videoIndex ? { ...v, analysis: finalAnalysis } : v) });
      } catch (e) {
        console.warn("Save failed after analysis:", e);
      }

    } catch (e) {
      console.error(e);
      alert("Analysis failed: " + e.message);
    } finally {
      // reset analyzing state
      if (mountedRef.current) setAnalyzingState(null);
    }
  };

  // Analyze all videos sequentially (queue). Each video gets individual analysis and save.
  const analyzeAllVideos = async () => {
    if (!current || !current.videos || current.videos.length === 0) {
      alert("No videos to analyze");
      return;
    }

    setAnalyzingState({ type: "all", idx: 0 });

    try {
      for (let i = 0; i < current.videos.length; i++) {
        if (!mountedRef.current) break;
        // update queue pointer
        setAnalyzingState({ type: "all", idx: i });
        // call single analyze for each video
        // We reuse analyzeVideo logic but avoid double-saving logic conflicts by doing inline here:
        const video = current.videos[i];
        if (!video.transcript) continue;

        try {
          let token = null;
          try {
            token = auth.currentUser ? await auth.currentUser.getIdToken() : null;
          } catch (e) {
            console.warn('Could not get id token', e);
          }
          const analyzeHeaders = { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) };
          const res = await fetch(`${BACKEND_URL}/analyze`, {
            method: "POST",
            headers: analyzeHeaders,
            body: JSON.stringify({ transcript: video.transcript }),
          });
          const data = await res.json();
          if (!res.ok) throw new Error(data.error || "Analysis failed");

          const finalAnalysis = data.final_analysis || data.analysis || (data.partial_summaries && data.partial_summaries.join("\n\n")) || "No analysis returned";

          // update current videos
          setCurrent((prev) => {
            const copy = { ...prev, videos: prev.videos.map((v, idx) => idx === i ? { ...v, analysis: finalAnalysis } : v) };
            return copy;
          });

          // persist after each video
          try {
            // read latest current from state via getSession? We call persistCurrentSession with the snapshot
            await persistCurrentSession({
              ...(current || {}),
              videos: (current && current.videos) ? current.videos.map((v, idx) => idx === i ? { ...v, analysis: finalAnalysis } : v) : []
            });
          } catch (e) {
            console.warn("Save failed after video analysis:", e);
          }

        } catch (err) {
          console.error("Failed to analyze video index", i, err);
          // continue queue (you may want to stop on error)
        }
      }

      alert("All videos analyzed (saved progress as each finished).");
    } catch (e) {
      console.error(e);
      alert("Analyze all failed: " + e.message);
    } finally {
      if (mountedRef.current) setAnalyzingState(null);
    }
  };

  // Run throughput test with three different LLM configs
  const runThroughputTest = async () => {
    if (!current || !current.videos || current.videos.length === 0 || !current.videos[0].transcript) {
      alert("No transcript available to test throughput");
      return;
    }

    const transcript = current.videos[0].transcript;
    if (transcript.trim().length === 0) {
      alert("Transcript is empty");
      return;
    }

    setRunningThroughputTest(true);
    setThroughputResults(null);

    const configs = [
      { name: "config_low_threads", n_threads: 2, n_batch: 64, n_gpu_layers: 20 },
      { name: "config_mid", n_threads: 6, n_batch: 128, n_gpu_layers: 30 },
      { name: "config_high_threads", n_threads: 12, n_batch: 256, n_gpu_layers: 40 }
    ];

    const results = [];

    try {
      for (const cfg of configs) {
        console.log(`Running throughput test for ${cfg.name}...`);

        let token = null;
        try {
          token = auth.currentUser ? await auth.currentUser.getIdToken() : null;
        } catch (e) {
          console.warn('Could not get id token', e);
        }
        const headers = { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) };

        const res = await fetch(`${BACKEND_URL}/analyze_with_config`, {
          method: "POST",
          headers,
          body: JSON.stringify({
            transcript,
            config: cfg,
            max_tokens: 300
          }),
        });

        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.error || `Server responded ${res.status}`);
        }

        results.push({
          config: cfg.name,
          metrics: data.metrics,
          config_params: cfg
        });

        console.log(`Completed ${cfg.name}:`, data.metrics);
      }

      setThroughputResults(results);
      console.log("Throughput test completed:", results);

    } catch (e) {
      console.error("Throughput test failed:", e);
      alert("Throughput test failed: " + e.message);
    } finally {
      setRunningThroughputTest(false);
    }
  };

  // Copy helper
  const copyToClipboard = async (text) => {
    if (!navigator.clipboard) {
      alert("Clipboard API not supported");
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      // small UX: show temporary message? For now alert.
      alert("Copied to clipboard");
    } catch {
      alert("Copy failed");
    }
  };

  // Title inline edit handling (clean UI)
  const onTitleChange = (newTitle) => {
    setCurrent((prev) => {
      if (!prev) return prev;
      return { ...prev, title: newTitle };
    });
  };

  const onTitleBlur = (fallbackTitle) => {
    setCurrent((prev) => {
      if (!prev) return prev;
      const t = (prev.title || "").trim();
      if (!t) {
        // fallback to first video title or provided fallback
        const fallback = fallbackTitle || (prev.videos?.[0]?.title) || "Untitled session";
        return { ...prev, title: fallback };
      }
      return prev;
    });
  };

  // UI helpers to decide button disabled states
  const isAnalyzingVideo = (idx) => {
    return analyzingState && ((analyzingState.type === "single" && analyzingState.idx === idx) || (analyzingState.type === "all" && analyzingState.idx === idx));
  };

  const analyzingAny = () => !!analyzingState;

  // Save current session explicitly (manual save)
  const saveCurrent = async () => {
    if (!current) return;
    try {
      console.log('saveCurrent: user', user);
      const id = await persistCurrentSession(current);
      console.log('saveCurrent: saved id', id);
      alert("Session saved.");
    } catch (e) {
      console.error(e);
      alert("Save failed: " + e.message);
    }
  };

  // Clear main panel (not delete history)
  const clearMain = () => {
    setCurrent(null);
    setUrlsText("");
    setAnalyzingState(null);
    setThroughputResults(null);
  };

  // Render helpers
  const renderLeftPanelVideos = () => {
    if (!current || !current.videos || current.videos.length === 0) {
      return <div className="panel-body"><em>No transcript loaded.</em></div>;
    }

    return (
      <>
        <div className="panel-body">
          {current.videos.map((v, idx) => (
            <div key={idx} style={{ marginBottom: 12 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <strong style={{ color: "#0b2240" }}>{v.title}</strong>
                <small style={{ color: "#6b7280" }}>{v.url ? "" : ""}</small>
              </div>
              <pre className="text-block" style={{ marginTop: 6 }}>{v.transcript || "No transcript available."}</pre>

              <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 6 }}>
                <button onClick={() => copyToClipboard(v.transcript || "")}>Copy Transcript</button>
                <button
                  onClick={() => analyzeVideo(idx)}
                  disabled={analyzingAny() || !v.transcript}
                >
                  {isAnalyzingVideo(idx) ? "Analyzing..." : "Analyze"}
                </button>
              </div>

              <hr style={{ marginTop: 12, border: "none", borderTop: "1px solid #eef2ff" }} />
            </div>
          ))}
        </div>
      </>
    );
  };

  const renderRightPanelAnalysis = () => {
    if (!current || !current.videos || current.videos.length === 0) {
      return <div className="panel-body"><em>No analysis yet.</em></div>;
    }

    return (
      <>
        <div className="panel-body">
          {current.videos.map((v, idx) => (
            <div key={idx} style={{ marginBottom: 12 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <strong style={{ color: "#0b2240" }}>{v.title}</strong>
                <small style={{ color: "#6b7280" }}>{/* placeholder for duration or id */}</small>
              </div>
              <pre className="text-block" style={{ marginTop: 6 }}>{v.analysis || "No analysis yet."}</pre>

              <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 6 }}>
                <button onClick={() => copyToClipboard(v.analysis || "")}>Copy Analysis</button>
              </div>

              <hr style={{ marginTop: 12, border: "none", borderTop: "1px solid #eef2ff" }} />
            </div>
          ))}
        </div>
      </>
    );
  };

  // JSX
  return (
    <div className="dashboard-root">
      {/* Imported-count banner */}
      {importedCount !== null && (
        <div className="imported-banner">
          Imported {importedCount} video{importedCount === 1 ? "" : "s"}. Processing may take some time for large playlists.
          <button className="imported-dismiss" onClick={() => setImportedCount(null)}>Dismiss</button>
        </div>
      )}
      <Sidebar
        collapsed={collapsed}
        toggle={toggle}
        sessions={sessions}
        onNew={onNew}
        onSelect={onSelect}
        currentId={current?.id}
        userEmail={user?.email}
        onLogout={onLogout}
        onDelete={handleDeleteSession}
      />

      <main className={`main-area ${collapsed ? "expanded" : ""}`}>
        <header className="main-header">
          <div style={{ display: "flex", flexDirection: "column" }}>
            {/* Inline editable title (looks like text) */}
            <input
              className="session-title-input"
              value={current?.title || ""}
              onChange={(e) => onTitleChange(e.target.value)}
              onBlur={() => onTitleBlur(current?.videos?.[0]?.title)}
              placeholder="Untitled session"
              style={{
                fontSize: 20,
                fontWeight: 600,
                border: "none",
                outline: "none",
                background: "transparent",
                padding: 0,
                marginBottom: 4,
                color: "#0b2240",
                width: "min(60vw, 720px)"
              }}
            />
            {/* remove email under the title as requested */}
          </div>

          <div className="header-actions">
            <button onClick={clearMain}>Clear</button>
            <button onClick={saveCurrent} disabled={!current}>Save</button>
          </div>
        </header>

        {/* debug box removed */}

        <section className="controls">
          <textarea
            placeholder="Enter YouTube links (one per line)..."
            value={urlsText}
            onChange={(e) => setUrlsText(e.target.value)}
            rows={4}
          />
          {loadingTranscripts && (
            <div className="fetching-indicator">
              <span className="spinner" /> Fetching transcripts...
            </div>
          )}
          <div className="controls-row">
            <button onClick={fetchTranscripts} disabled={loadingTranscripts}>
              {loadingTranscripts ? "Fetching..." : "Get Transcripts"}
            </button>
            <button onClick={onNew}>Start Blank Session</button>
            <button onClick={analyzeAllVideos} disabled={analyzingAny() || !(current && current.videos && current.videos.length > 0)}>
              {analyzingState && analyzingState.type === "all" ? `Analyzing ${analyzingState.idx + 1}/${current?.videos?.length}` : "Analyze All"}
            </button>
          </div>

          {/* Throughput Test Section - Admin Only */}
          {isAdmin && (
            <div className="throughput-test-section" style={{ marginTop: 20, padding: 12, border: "1px solid #e5e7eb", borderRadius: 8 }}>
              <h4 style={{ margin: 0, marginBottom: 8 }}>LLM Throughput Test (Admin Only)</h4>
              <p style={{ margin: 0, marginBottom: 12, fontSize: 14, color: "#6b7280" }}>
                Test throughput with different LLM parameters using the current transcript.
              </p>
              <button
                onClick={runThroughputTest}
                disabled={runningThroughputTest || !current || !current.videos || !current.videos[0]?.transcript}
                style={{ marginBottom: 12 }}
              >
                {runningThroughputTest ? "Running Test..." : "Run Throughput Test"}
              </button>

              {throughputResults && (
                <div className="throughput-results">
                  <h5>Results:</h5>
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
                    <thead>
                      <tr style={{ backgroundColor: "#f9fafb" }}>
                        <th style={{ border: "1px solid #e5e7eb", padding: 8, textAlign: "left" }}>Config</th>
                        <th style={{ border: "1px solid #e5e7eb", padding: 8, textAlign: "right" }}>Latency (s)</th>
                        <th style={{ border: "1px solid #e5e7eb", padding: 8, textAlign: "right" }}>Tokens/sec</th>
                        <th style={{ border: "1px solid #e5e7eb", padding: 8, textAlign: "right" }}>Total Tokens</th>
                        <th style={{ border: "1px solid #e5e7eb", padding: 8, textAlign: "right" }}>Quality (1-5)</th>
                        <th style={{ border: "1px solid #e5e7eb", padding: 8, textAlign: "right" }}>Grounded (1-5)</th>
                        <th style={{ border: "1px solid #e5e7eb", padding: 8, textAlign: "right" }}>Concise (1-5)</th>
                        <th style={{ border: "1px solid #e5e7eb", padding: 8, textAlign: "right" }}>Insight (1-5)</th>
                        <th style={{ border: "1px solid #e5e7eb", padding: 8, textAlign: "left" }}>Reason</th>
                      </tr>
                    </thead>
                    <tbody>
                      {throughputResults.map((result, idx) => (
                        <tr key={idx}>
                          <td style={{ border: "1px solid #e5e7eb", padding: 8 }}>{result.config}</td>
                          <td style={{ border: "1px solid #e5e7eb", padding: 8, textAlign: "right" }}>{result.metrics.latency_seconds.toFixed(2)}</td>
                          <td style={{ border: "1px solid #e5e7eb", padding: 8, textAlign: "right" }}>{result.metrics.throughput_tokens_per_second.toFixed(2)}</td>
                          <td style={{ border: "1px solid #e5e7eb", padding: 8, textAlign: "right" }}>{result.metrics.total_tokens}</td>
                          <td style={{ border: "1px solid #e5e7eb", padding: 8, textAlign: "right" }}>{result.metrics.quality_score !== null ? result.metrics.quality_score : 'N/A'}</td>
                          <td style={{ border: "1px solid #e5e7eb", padding: 8, textAlign: "right" }}>{result.metrics.evaluation?.groundedness || 'N/A'}</td>
                          <td style={{ border: "1px solid #e5e7eb", padding: 8, textAlign: "right" }}>{result.metrics.evaluation?.conciseness || 'N/A'}</td>
                          <td style={{ border: "1px solid #e5e7eb", padding: 8, textAlign: "right" }}>{result.metrics.evaluation?.insight || 'N/A'}</td>
                          <td style={{ border: "1px solid #e5e7eb", padding: 8, textAlign: "left", fontSize: 12, maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis" }} title={result.metrics.evaluation?.reason || 'N/A'}>
                            {result.metrics.evaluation?.reason || 'N/A'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <button onClick={() => setThroughputResults(null)} style={{ marginTop: 8, fontSize: 12 }}>
                    Clear Results
                  </button>
                </div>
              )}
            </div>
          )}
        </section>

        <section className="workspace">
          <div className="panel left-panel" style={{ flex: 1 }}>
            <h3>Transcripts</h3>
            {renderLeftPanelVideos()}
          </div>

          <div className="panel right-panel" style={{ flex: 1 }}>
            <h3>Analysis</h3>
            {renderRightPanelAnalysis()}
          </div>
        </section>
      </main>
    </div>
  );
}
