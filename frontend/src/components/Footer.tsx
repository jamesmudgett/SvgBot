import { Link } from "react-router-dom";

export default function Footer() {
  return (
    <footer className="site-footer">
      <nav className="site-footer-nav" aria-label="Legal and links">
        <Link to="/terms">Terms of Service</Link>
        <Link to="/privacy">Privacy Policy</Link>
        <a href="https://github.com/jamesmudgett/SvgBot" target="_blank" rel="noreferrer">
          GitHub
        </a>
        <a href="https://x.com/_svgbot" target="_blank" rel="noreferrer">
          X
        </a>
      </nav>
    </footer>
  );
}
