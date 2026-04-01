"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

type AuthMode = "login" | "signup" | "reset";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<AuthMode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    if (!email || (mode !== "reset" && !password)) {
      return;
    }

    setIsSubmitting(true);
    setErrorMessage(null);
    setSuccessMessage(null);

    try {
      const endpoint =
        mode === "login"
          ? "/api/auth/login"
          : mode === "signup"
            ? "/api/auth/signup"
            : "/api/auth/reset-password";

      const payload =
        mode === "reset"
          ? { email }
          : mode === "signup"
            ? { email, password, fullName }
            : { email, password };

      const response = await fetch(endpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        const data = (await response.json()) as { error?: string };
        setErrorMessage(data.error ?? "Unable to sign in");
        setIsSubmitting(false);
        return;
      }

      if (mode === "reset") {
        setSuccessMessage("Password reset email sent. Check your inbox.");
        setIsSubmitting(false);
        return;
      }

      if (mode === "signup") {
        const data = (await response.json()) as { needsEmailConfirmation?: boolean };

        if (data.needsEmailConfirmation) {
          setSuccessMessage("Account created. Confirm your email before signing in.");
          setMode("login");
          setIsSubmitting(false);
          return;
        }
      }

      router.push("/dashboard");
      router.refresh();
    } catch {
      setErrorMessage("Unable to reach authentication service");
      setIsSubmitting(false);
    }
  };

  return (
    <main className="mx-auto flex min-h-[70vh] w-full max-w-md flex-col items-stretch justify-center p-6">
      <h1 className="text-2xl font-semibold">Login</h1>
      <p className="mt-2 text-sm text-zinc-600">
        Sign in to access Siam Command AI Center.
      </p>
      <div className="mt-6 flex gap-2 text-sm">
        <button
          type="button"
          onClick={() => setMode("login")}
          className={`rounded-md px-3 py-2 ${mode === "login" ? "bg-zinc-900 text-white" : "bg-zinc-100 text-zinc-700"}`}
        >
          Sign in
        </button>
        <button
          type="button"
          onClick={() => setMode("signup")}
          className={`rounded-md px-3 py-2 ${mode === "signup" ? "bg-zinc-900 text-white" : "bg-zinc-100 text-zinc-700"}`}
        >
          Create account
        </button>
        <button
          type="button"
          onClick={() => setMode("reset")}
          className={`rounded-md px-3 py-2 ${mode === "reset" ? "bg-zinc-900 text-white" : "bg-zinc-100 text-zinc-700"}`}
        >
          Reset password
        </button>
      </div>
      <form onSubmit={handleSubmit} className="mt-6 space-y-4">
        {mode === "signup" ? (
          <div className="space-y-2">
            <label htmlFor="fullName" className="text-sm font-medium text-zinc-800">
              Full name
            </label>
            <input
              id="fullName"
              type="text"
              value={fullName}
              onChange={(event) => setFullName(event.target.value)}
              className="w-full rounded-md border border-zinc-300 px-3 py-2 text-sm outline-none transition focus:border-zinc-500"
            />
          </div>
        ) : null}
        <div className="space-y-2">
          <label htmlFor="email" className="text-sm font-medium text-zinc-800">
            Email
          </label>
          <input
            id="email"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            autoComplete="email"
            required
            className="w-full rounded-md border border-zinc-300 px-3 py-2 text-sm outline-none transition focus:border-zinc-500"
          />
        </div>
        {mode !== "reset" ? (
          <div className="space-y-2">
            <label htmlFor="password" className="text-sm font-medium text-zinc-800">
              Password
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              required
              className="w-full rounded-md border border-zinc-300 px-3 py-2 text-sm outline-none transition focus:border-zinc-500"
            />
          </div>
        ) : null}
        <button
          type="submit"
          disabled={isSubmitting}
          className="w-full rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-zinc-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {isSubmitting
            ? mode === "reset"
              ? "Sending..."
              : mode === "signup"
                ? "Creating..."
                : "Signing in..."
            : mode === "reset"
              ? "Send reset email"
              : mode === "signup"
                ? "Create account"
                : "Sign in"}
        </button>
        {errorMessage ? (
          <p className="text-sm text-red-600" role="alert">
            {errorMessage}
          </p>
        ) : null}
        {successMessage ? (
          <p className="text-sm text-emerald-600" role="status">
            {successMessage}
          </p>
        ) : null}
      </form>
    </main>
  );
}
