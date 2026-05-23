import LegalPage from "../components/LegalPage";

export default function PrivacyPage() {
  return (
    <LegalPage title="Privacy Policy">
      <p>
        This Privacy Policy describes how SvgBot (&quot;we&quot;, &quot;us&quot;) handles
        information when you use the SvgBot web application and API (&quot;Service&quot;).
      </p>

      <h2>1. Information we process</h2>
      <p>Depending on how you use the Service, we may process:</p>
      <ul>
        <li>
          <strong>Images you submit</strong>, via file upload or image URL, for the purpose of
          vectorization.
        </li>
        <li>
          <strong>Conversion metadata</strong>, such as job identifiers, engine choices, quality
          settings, timing, and scoring metrics needed to run and display results.
        </li>
        <li>
          <strong>Technical data</strong>, such as IP address, browser type, and request logs, when
          the Service is operated on a public server.
        </li>
        <li>
          <strong>Payment-related data</strong>, when API payments are enabled, as required by the
          payment provider (for example MPP or x402). We do not store full payment card numbers.
        </li>
      </ul>

      <h2>2. How we use information</h2>
      <p>We use submitted information to:</p>
      <ul>
        <li>Run vectorization jobs and return SVG results.</li>
        <li>Operate, secure, and troubleshoot the Service.</li>
        <li>Process payments for paid API access when enabled.</li>
        <li>Improve reliability and detect abuse.</li>
      </ul>
      <p>
        We do not use your uploaded images to train machine learning models unless we explicitly
        say otherwise in writing.
      </p>

      <h2>3. Retention</h2>
      <p>
        Conversion jobs and associated files are kept only as long as needed to complete the
        request, serve downloads, and maintain reasonable operational logs. Job data may be deleted
        automatically after a short retention period on hosted deployments. If you self-host SvgBot,
        retention is controlled by your configuration.
      </p>

      <h2>4. Sharing</h2>
      <p>We do not sell your personal information. We may share data:</p>
      <ul>
        <li>With infrastructure providers that host the Service.</li>
        <li>With payment processors when you pay for API access.</li>
        <li>When required by law or to protect the rights and safety of users and the Service.</li>
      </ul>
      <p>
        If you submit an image by URL, the Service fetches that URL from its servers. The remote
        host may log that request.
      </p>

      <h2>5. Local and self-hosted use</h2>
      <p>
        When you run SvgBot locally or on your own infrastructure, image data typically stays on
        your machine or network. This policy applies to information handled by the operator of the
        instance you are using.
      </p>

      <h2>6. Cookies and analytics</h2>
      <p>
        The SvgBot web UI does not require an account. We do not use third-party advertising
        cookies. Basic server logs or optional analytics on a hosted deployment, if any, are used
        only for operations and security.
      </p>

      <h2>7. Your choices</h2>
      <p>
        Do not submit content you do not want processed. For hosted deployments, you may contact us
        to request deletion of operational logs tied to your use where feasible.
      </p>

      <h2>8. Children</h2>
      <p>
        The Service is not directed at children under 13. We do not knowingly collect personal
        information from children.
      </p>

      <h2>9. Changes</h2>
      <p>
        We may update this Privacy Policy from time to time. The &quot;Last updated&quot; date at
        the top reflects the latest revision.
      </p>

      <h2>10. Contact</h2>
      <p>
        Privacy questions:{" "}
        <a href="https://x.com/_svgbot" target="_blank" rel="noreferrer">
          @_svgbot on X
        </a>
        .
      </p>
    </LegalPage>
  );
}
