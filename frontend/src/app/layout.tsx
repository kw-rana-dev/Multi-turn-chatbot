import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "RAG Studio — AI Knowledge Base",
  description: "A RAG-powered chat application with semantic search over your documents. Built with Next.js, FastAPI, PostgreSQL + pgvector.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
