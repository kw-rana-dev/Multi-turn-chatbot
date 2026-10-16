"use client";

import { useState, useEffect } from "react";
import styles from "./page.module.css";
import ChatPanel from "@/components/ChatPanel";
import DocumentsPanel from "@/components/DocumentsPanel";
import SearchPanel from "@/components/SearchPanel";

type Tab = "chat" | "documents" | "search";

export default function Home() {
  const [activeTab, setActiveTab] = useState<Tab>("chat");
  const [backendStatus, setBackendStatus] = useState<"checking" | "ok" | "error">("checking");

  useEffect(() => {
    fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/health`)
      .then((r) => setBackendStatus(r.ok ? "ok" : "error"))
      .catch(() => setBackendStatus("error"));
  }, []);

  return (
    <div className={styles.shell}>
      {/* Sidebar */}
      <aside className={styles.sidebar}>
        <div className={styles.sidebarLogo}>
          <div className={styles.logoIcon}>⚡</div>
          <div>
            <div className={styles.logoTitle}>RAG Studio</div>
            <div className={styles.logoSub}>AI Knowledge Base</div>
          </div>
        </div>

        <nav className={styles.nav}>
          {(["chat", "documents", "search"] as Tab[]).map((tab) => (
            <button
              key={tab}
              id={`nav-${tab}`}
              className={`${styles.navItem} ${activeTab === tab ? styles.navItemActive : ""}`}
              onClick={() => setActiveTab(tab)}
            >
              <span className={styles.navIcon}>
                {tab === "chat" ? "💬" : tab === "documents" ? "📄" : "🔍"}
              </span>
              <span className={styles.navLabel}>
                {tab === "chat" ? "Chat" : tab === "documents" ? "Documents" : "Search"}
              </span>
            </button>
          ))}
        </nav>

        <div className={styles.sidebarFooter}>
          <div className={styles.statusDot}>
            <span
              className={`${styles.dot} ${
                backendStatus === "ok"
                  ? styles.dotGreen
                  : backendStatus === "error"
                  ? styles.dotRed
                  : styles.dotYellow
              }`}
            />
            <span className={styles.statusLabel}>
              {backendStatus === "ok" ? "API Connected" : backendStatus === "error" ? "API Offline" : "Connecting…"}
            </span>
          </div>
          <div className={styles.stackBadges}>
            <span className="badge badge-purple">FastAPI</span>
            <span className="badge badge-blue">pgvector</span>
            <span className="badge badge-green">MinIO</span>
          </div>
        </div>
      </aside>

      {/* Main content */}
      <main className={styles.main}>
        {activeTab === "chat" && <ChatPanel />}
        {activeTab === "documents" && <DocumentsPanel />}
        {activeTab === "search" && <SearchPanel />}
      </main>
    </div>
  );
}
