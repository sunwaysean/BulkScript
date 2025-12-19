import React from "react";
import "./Sidebar.css";

export default function Sidebar({
  collapsed,
  toggle,
  sessions,
  onNew,
  onSelect,
  currentId,
  userEmail,
  onLogout,
  onDelete
}) {
  return (
    <aside className={`sidebar ${collapsed ? "collapsed" : ""}`}>
      <div className="sidebar-header">
        <div className="sidebar-top">
          <button className="hamburger" onClick={toggle} aria-label="Toggle sidebar">
            <span style={{ fontSize: '20px' }}>{collapsed ? "»" : "☰"}</span>
          </button>
          {!collapsed && <h1 className="brand">BulkScript</h1>}
        </div>

        <div className="sidebar-actions">
          <button className="new-session" onClick={onNew} aria-label="New session">
            <span style={{ fontSize: '18px', fontWeight: 'bold' }}>+</span>
            <span className="btn-text">New Session</span>
          </button>
        </div>
      </div>

      <div className="sidebar-body">
        <div className="history-list" role="list">
          {!sessions || sessions.length === 0 ? (
            <p className="muted">{collapsed ? "..." : "No sessions yet"}</p>
          ) : (
            sessions.map((s) => (
              <div
                key={s.id}
                role="listitem"
                className={`history-item ${s.id === currentId ? "active" : ""}`}
                onClick={() => onSelect(s)}
                title={s.title}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, width: '100%' }}>
                  <div style={{ flex: 1, overflow: 'hidden' }}>
                    <div className="title">{s.title || (s.urls && s.urls[0]) || "Untitled"}</div>
                    <div className="meta">{s.createdAt?.toDate ? s.createdAt.toDate().toLocaleString() : ""}</div>
                  </div>
                  <div style={{ flex: '0 0 auto' }}>
                    <button
                      className="session-actions"
                      onClick={(e) => {
                        e.stopPropagation();
                        if (onDelete) onDelete(s);
                      }}
                      title="More"
                      aria-label="Session actions"
                    >
                      ⋯
                    </button>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      <div className="sidebar-footer">
        <div className="footer-inner">
          <div className="user-email" title={userEmail}>{userEmail}</div>
          <button className="logout" onClick={onLogout} aria-label="Logout">
            {collapsed ? <span style={{fontSize: '16px'}}>⎋</span> : 'Logout'}
          </button>
        </div>
      </div>
    </aside>
  );
}