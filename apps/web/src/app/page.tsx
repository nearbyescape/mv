import { Dashboard } from "@/components/dashboard";
import { authRequired } from "@/lib/access";
import { backend } from "@/lib/backend";
import { redirect } from "next/navigation";
export const dynamic = "force-dynamic";
export default async function Home() {
  if (!authRequired()) return <Dashboard />;
  let response: Response;
  try {
    response = await backend("/v1/auth/me");
  } catch {
    return (
      <main className="auth-page">
        <section className="auth-form-panel">
          <div className="auth-form-wrap">
            <h1>Workspace temporarily unavailable</h1>
            <p>
              The account service could not be reached. Please try again
              shortly.
            </p>
            <a className="secondary-button" href="/">
              Retry
            </a>
          </div>
        </section>
      </main>
    );
  }
  if (response.status === 401) redirect("/login");
  if (!response.ok)
    return (
      <main className="auth-page">
        <section className="auth-card">
          <h1>Workspace temporarily unavailable</h1>
          <p>Account access could not be verified. Please retry shortly.</p>
          <a href="/">Retry</a>
        </section>
      </main>
    );
  const account = await response.json();
  return <Dashboard initialUser={account.user} authenticationRequired />;
}
