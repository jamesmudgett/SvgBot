import { Link } from "react-router-dom";

type LegalPageProps = {
  title: string;
  children: React.ReactNode;
};

export default function LegalPage({ title, children }: LegalPageProps) {
  return (
    <div className="legal-page">
      <header className="legal-header">
        <Link to="/" className="legal-home-link">
          <img src="/assets/SvgBot.png" alt="SvgBot" className="site-logo legal-logo" />
        </Link>
        <h1>{title}</h1>
        <p className="legal-updated">Last updated: May 23, 2026</p>
      </header>
      <article className="legal-content panel">{children}</article>
    </div>
  );
}
