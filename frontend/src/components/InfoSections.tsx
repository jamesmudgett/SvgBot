import { AUTO_ENGINES, ENGINE_OPTIONS } from "../engineOptions";

export default function InfoSections() {
  return (
    <>
      <section className="info-section" aria-labelledby="how-it-works-heading">
        <h2 id="how-it-works-heading">How it works</h2>
        <p className="info-lead">
          SvgBot treats vectorization as a search-and-refine problem, not a single pass through one
          algorithm.
        </p>

        <div className="info-phases">
          <article className="info-phase">
            <h3>Phase 1: Preprocess &amp; classify</h3>
            <p>
              The input image is loaded, resized (long edge capped at 2048 px), and analyzed for
              unique color count and edge density. That classifies it as logo, illustration, or
              photo, which selects VTracer parameter grids and whether the smooth-curve pipeline
              runs.
            </p>
          </article>

          <article className="info-phase">
            <h3>Phase 2: Multi-engine candidate generation</h3>
            <p>
              By default, SvgBot uses <strong>Auto</strong>: it runs every engine below and keeps
              the highest-scoring candidate. Pick a single engine when you know what fits your
              image (for example <strong>VTracer smooth</strong> for logos and flat-fill brand
              marks).
            </p>
            <dl className="info-engine-list">
              {ENGINE_OPTIONS.map((opt) => (
                <div key={opt.value} className="info-engine-item">
                  <dt>{opt.selectLabel.split(" (")[0]}</dt>
                  <dd>
                    <span className="info-engine-best-for">Best for: {opt.bestFor}</span>
                    {opt.description}
                  </dd>
                </div>
              ))}
            </dl>
            <p className="info-engine-auto-heading">
              <strong>Inside Auto:</strong> SvgBot runs these candidates in parallel, then ranks them
              with DinoScore (and an LPIPS tiebreak on logos when scores are close):
            </p>
            <ul className="info-engine-auto-list">
              {AUTO_ENGINES.map((opt) => (
                <li key={opt.selectLabel}>
                  <strong>{opt.selectLabel}</strong> ({opt.bestFor.toLowerCase()}): {opt.description}
                </li>
              ))}
            </ul>
            <p>
              Each candidate is rasterized back to pixels and ranked with{" "}
              <strong>DinoScore</strong> (ResNet-50 embedding cosine distance, primary metric) and{" "}
              <strong>LPIPS</strong> (AlexNet perceptual distance). The winner becomes the base SVG
              for refinement.
            </p>
          </article>

          <article className="info-phase">
            <h3>Phase 3: Iterative residual diff, vectorize, merge</h3>
            <p>
              Even the best single-pass SVG leaves pixels that do not match the source: missing
              letter counters, softened corners, anti-aliasing gaps, small color patches. SvgBot
              closes that gap with up to 20 refinement passes. Each pass:
            </p>
            <ol>
              <li>Rasterizes the current best SVG back to a bitmap at source dimensions.</li>
              <li>
                Computes a per-pixel RGB diff to build a residual mask of pixels that still differ.
              </li>
              <li>
                Filters the mask (edge exclusion for anti-aliasing halos, connected-component
                filtering for speckle).
              </li>
              <li>Extracts only the differing pixels into a transparent RGBA image.</li>
              <li>Vectorizes the residual with VTracer using pass-specific parameters.</li>
              <li>
                Merges corrective paths into the base SVG inside a{" "}
                <code>&lt;g class=&quot;vb-refine&quot;&gt;</code> group, with coordinate transforms
                when engines use different viewBox units.
              </li>
              <li>
                Re-scores with DinoScore and keeps the merge only if the score improves by a minimum
                delta.
              </li>
            </ol>
            <p>
              Six pass variants cycle from conservative (large interior defects) to aggressive
              (fine near-edge defects). The loop stops when residual coverage is negligible, three
              consecutive passes fail to improve the score, or the pass limit is reached. Accepted
              passes appear in the result as refine passes and patched coverage.
            </p>
          </article>

          <article className="info-phase">
            <h3>Phase 4: Fontless sanitize</h3>
            <p>
              With fontless output enabled (default), <code>&lt;text&gt;</code> elements and font
              references are stripped or converted to paths so the SVG is pure geometry with no
              embedded fonts or system-font dependencies.
            </p>
          </article>
        </div>
      </section>

      <section className="info-section" aria-labelledby="agents-pricing-heading">
        <h2 id="agents-pricing-heading">Agents and Pricing</h2>
        <p className="info-lead">
          Autonomous agents can pay per conversion over HTTP using{" "}
          <a href="https://mpp.dev" target="_blank" rel="noreferrer">
            MPP
          </a>{" "}
          (Tempo/Stripe) or{" "}
          <a href="https://docs.x402.org" target="_blank" rel="noreferrer">
            x402
          </a>
          . The web UI above is free for local use; paid access applies when the server operator
          enables payments.
        </p>

        <div className="info-pricing-card">
          <p className="info-price">
            <strong>$0.50</strong> per conversion
          </p>
          <p className="info-price-note">
            One charge per successful <code>POST /api/vectorize</code>. Pricing is the same for
            every quality tier; quality may change output speed. Polling and download endpoints are
            free after the job is created.
          </p>
        </div>

        <h3 className="info-subheading">Discovery</h3>
        <ul className="info-endpoints">
          <li>
            <a href="/.well-known/agent-api" target="_blank" rel="noreferrer">
              <code>GET /.well-known/agent-api</code>
            </a>
            : machine-readable workflow, pricing, and MPP/x402 payment steps
          </li>
          <li>
            <a href="/.well-known/mpp-discovery" target="_blank" rel="noreferrer">
              <code>GET /.well-known/mpp-discovery</code>
            </a>
            : MPP payment discovery document
          </li>
          <li>
            <a href="/health" target="_blank" rel="noreferrer">
              <code>GET /health</code>
            </a>
            : health check and StarVector availability
          </li>
        </ul>

        <h3 className="info-subheading">Agent workflow</h3>
        <ol className="info-workflow">
          <li>
            Discover pricing and protocols via{" "}
            <a href="/.well-known/agent-api">/.well-known/agent-api</a>.
          </li>
          <li>
            Pay (when <code>payment.enabled</code>) by attaching MPP or x402 credentials to the
            vectorize request.
          </li>
          <li>
            Start conversion: <code>POST /api/vectorize</code> with a file or{" "}
            <code>image_url</code>, plus <code>quality</code>, <code>engine</code>, and{" "}
            <code>fontless</code>.
          </li>
          <li>
            Poll <code>GET /api/jobs/&#123;id&#125;</code> until status is completed or failed
            (includes <code>refine_passes</code>, <code>refine_coverage</code>, and{" "}
            <code>dino_score</code>).
          </li>
          <li>
            Download the SVG via <code>GET /api/jobs/&#123;id&#125;/svg</code> or use{" "}
            <code>result.svg</code> from the job payload.
          </li>
        </ol>

        <p className="info-footnote">
          Server operators enable payments with <code>PAYMENTS_ENABLED=true</code> and MPP/x402
          credentials in <code>backend/.env</code>. Full agent instructions are in the project{" "}
          <code>docs/AGENT_API.md</code>.
        </p>
      </section>
    </>
  );
}
