import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import SelectPage from "@/pages/Select";
import TalkPage from "@/pages/Talk";
import ProgressPage from "@/pages/Progress";
import ReviewPage from "@/pages/Review";
import BooksPage from "@/pages/Books";
import SessionsPage from "@/pages/Sessions";
import SetupRequiredPage from "@/pages/SetupRequired";
import { HealthBanner } from "@/components/HealthBanner";
import { CapabilitiesProvider } from "@/components/CapabilitiesProvider";
import { useCapabilities } from "@/lib/capabilities";
import { t } from "@/i18n";

function Shell() {
  const { health, loading } = useCapabilities();
  if (loading) {
    return (
      <div className="min-h-full flex items-center justify-center">
        <p className="text-ink-400 animate-pulse">{t("app.loading")}</p>
      </div>
    );
  }
  // Without a chat model nothing works: show how to configure one.
  if (health?.status === "setup_required") return <SetupRequiredPage />;
  return (
    <>
      <HealthBanner />
      <Routes>
        <Route path="/" element={<SelectPage />} />
        <Route path="/talk" element={<TalkPage />} />
        <Route path="/progress" element={<ProgressPage />} />
        <Route path="/review" element={<ReviewPage />} />
        <Route path="/books" element={<BooksPage />} />
        <Route path="/sessions" element={<SessionsPage />} />
        <Route path="/sessions/:id" element={<SessionsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  );
}

export default function App() {
  return (
    <CapabilitiesProvider>
      <BrowserRouter>
        <Shell />
      </BrowserRouter>
    </CapabilitiesProvider>
  );
}
