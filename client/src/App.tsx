import Chat from "./components/chat"
import EvalLabeler from "./components/eval-labeler"
import Analytics from "./components/analytics"

export default function App() {
  const params = new URLSearchParams(window.location.search)
  const evalMode = params.get("mode") === "eval"
  const analyticsMode = params.get("mode") === "analytics"

  if (analyticsMode) return <Analytics />
  if (evalMode) return <EvalLabeler />
  return <Chat />
}