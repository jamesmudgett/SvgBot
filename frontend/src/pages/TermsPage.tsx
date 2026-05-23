import LegalPage from "../components/LegalPage";

export default function TermsPage() {
  return (
    <LegalPage title="Terms of Service">
      <p>
        These Terms of Service (&quot;Terms&quot;) govern your use of SvgBot, including the web
        application at svg.bot and any hosted or self-hosted SvgBot API (&quot;Service&quot;). By
        using the Service, you agree to these Terms.
      </p>

      <h2>1. The Service</h2>
      <p>
        SvgBot converts raster images into fontless SVG using multiple vectorization engines,
        perceptual scoring, and optional refinement. The web UI is provided for convenience. When
        payments are enabled on a deployment, programmatic access via the HTTP API may require
        payment through supported protocols such as MPP or x402.
      </p>

      <h2>2. Your content</h2>
      <p>
        You retain ownership of images you upload or submit by URL. You represent that you have the
        rights needed to submit that content and to receive a converted SVG output. Do not submit
        content that infringes copyright, violates privacy, or is unlawful.
      </p>
      <p>
        You grant SvgBot a limited license to process your submitted images solely to provide the
        Service, including temporary storage in memory or on disk for the duration of a conversion
        job.
      </p>

      <h2>3. Acceptable use</h2>
      <p>You agree not to:</p>
      <ul>
        <li>Use the Service to violate any law or third-party rights.</li>
        <li>Attempt to disrupt, overload, or reverse engineer the Service.</li>
        <li>Circumvent rate limits, payment requirements, or access controls.</li>
        <li>Submit malware, abusive content, or content you are not authorized to convert.</li>
      </ul>

      <h2>4. API pricing and payments</h2>
      <p>
        When payment is enabled on a deployment, paid API conversions are billed per successful
        conversion as described in the Service discovery documents (for example{" "}
        <code>/.well-known/agent-api</code>). Prices, supported payment methods, and availability
        may change. Refunds, if any, are handled at the discretion of the operator of the
        deployment you are using.
      </p>

      <h2>5. Output and accuracy</h2>
      <p>
        SvgBot aims for high-fidelity vectorization but does not guarantee that every output will
        match your expectations or be suitable for every use case. You are responsible for reviewing
        SVG output before use in production, print, or commercial work.
      </p>

      <h2>6. Disclaimer</h2>
      <p>
        THE SERVICE IS PROVIDED &quot;AS IS&quot; AND &quot;AS AVAILABLE&quot; WITHOUT WARRANTIES OF
        ANY KIND, WHETHER EXPRESS OR IMPLIED, INCLUDING MERCHANTABILITY, FITNESS FOR A PARTICULAR
        PURPOSE, AND NON-INFRINGEMENT. SvgBot is not liable for indirect, incidental, special,
        consequential, or punitive damages, or for loss of data, profits, or business arising from
        your use of the Service.
      </p>

      <h2>7. Self-hosted deployments</h2>
      <p>
        If you run SvgBot yourself, you are responsible for your instance, infrastructure, data
        handling, and compliance with applicable laws. These Terms apply to your use of the SvgBot
        software; your users may be subject to additional terms you publish.
      </p>

      <h2>8. Changes</h2>
      <p>
        We may update these Terms from time to time. Continued use of the Service after changes
        become effective constitutes acceptance of the updated Terms.
      </p>

      <h2>9. Contact</h2>
      <p>
        Questions about these Terms:{" "}
        <a href="https://x.com/_svgbot" target="_blank" rel="noreferrer">
          @_svgbot on X
        </a>
        .
      </p>
    </LegalPage>
  );
}
