import Chat from "./components/chat"
import EvalLabeler from "./components/eval-labeler"

export default function App() {
  const params = new URLSearchParams(window.location.search)
  const evalMode = params.get("mode") === "eval"

  return evalMode ? <EvalLabeler /> : <Chat />
}