import { Route, Routes } from "react-router-dom";
import Footer from "./components/Footer";
import { EDITOR_ENABLED } from "./config";
import EditorPage from "./pages/EditorPage";
import HomePage from "./pages/HomePage";
import PrivacyPage from "./pages/PrivacyPage";
import TermsPage from "./pages/TermsPage";

export default function App() {
  return (
    <>
      <Routes>
        <Route path="/" element={<HomePage />} />
        {EDITOR_ENABLED && (
          <Route path="/editor/:jobId" element={<EditorPage />} />
        )}
        <Route path="/terms" element={<TermsPage />} />
        <Route path="/privacy" element={<PrivacyPage />} />
      </Routes>
      <Footer />
    </>
  );
}
