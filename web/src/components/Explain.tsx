// One or two lines of inline explanation, present where an AI concept is
// used. The reader knows markets. These explain the AI layers, never trading.
export default function Explain({ children }: { children: React.ReactNode }) {
  return <p className="explain">{children}</p>;
}
