import { StyleSheet } from "react-native";

export const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  content: {
    paddingHorizontal: 24,
    paddingTop: 32,
    paddingBottom: 32,
  },
  title: {
    fontSize: 32,
    fontWeight: "700",
  },
  loader: {
    marginTop: 16,
  },
  secondaryText: {
    fontSize: 16,
    marginTop: 8,
  },
  errorText: {
    fontSize: 16,
    marginTop: 12,
  },
  list: {
    marginTop: 16,
  },
  card: {
    marginTop: 16,
    padding: 20,
    borderWidth: 1,
    borderRadius: 12,
  },
  name: {
    fontSize: 18,
    fontWeight: "600",
  },
  // Plain, non-interactive status line for a hidden category -- same
  // fontWeight/marginTop as secondaryText, tinted like the destructive
  // color used elsewhere (see goals.styles.ts deleteButton) so "Hidden" is
  // unmistakable without looking like a tappable control (no border/box,
  // matching how budgets.styles.ts's exceededText emphasizes plain text).
  hiddenStatusText: {
    fontSize: 16,
    marginTop: 8,
    fontWeight: "600",
    color: "#cc3333",
  },
});
