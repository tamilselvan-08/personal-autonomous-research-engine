import { Bot } from "lucide-react";

import { ComingSoon } from "@/components/layout/coming-soon";

export const metadata = { title: "AI Providers" };

export default function AIProvidersPage() {
  return (
    <ComingSoon
      title="AI Providers"
      icon={Bot}
      summary="Connect your own language-model accounts. PARE will use them to plan and extract research, with automatic fallback between providers."
      planned={[
        "OpenAI, Anthropic, Google Gemini, xAI, DeepSeek, Mistral and OpenAI-compatible endpoints",
        "Encrypted API key storage; keys are never shown again after saving",
        "Connection tests, primary and fallback models, health and usage",
      ]}
    />
  );
}
