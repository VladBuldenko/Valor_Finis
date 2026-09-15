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
  // "Add Category" CTA on the management screen, and the primary "Save
  // category" action on the create/edit forms -- same shape as
  // goals.styles.ts / budgets.styles.ts's `button`.
  button: {
    alignItems: "center",
    borderWidth: 1,
    borderRadius: 10,
    paddingVertical: 14,
    marginTop: 16,
  },
  buttonText: {
    fontSize: 16,
    fontWeight: "600",
  },
  // Compact per-card action control on the Categories list -- doubles as
  // "Edit" for a custom category and "Hide"/"Show" for a default category
  // (the two are mutually exclusive per category, see categories-screen.tsx),
  // smaller than the full-width `button` so it reads as a secondary card
  // action. Mirrors goals.styles.ts's / budgets.styles.ts's editButton.
  editButton: {
    alignSelf: "flex-start",
    alignItems: "center",
    borderWidth: 1,
    borderRadius: 8,
    paddingVertical: 8,
    paddingHorizontal: 14,
    marginTop: 12,
  },
  editButtonText: {
    fontSize: 14,
    fontWeight: "600",
  },
  // Compact per-card "Delete" control for a custom category, sized like
  // `editButton` but tinted to read as destructive -- mirrors
  // budgets.styles.ts's / goals.styles.ts's deleteButton exactly.
  deleteButton: {
    alignSelf: "flex-start",
    alignItems: "center",
    borderWidth: 1,
    borderRadius: 8,
    paddingVertical: 8,
    paddingHorizontal: 14,
    marginTop: 8,
    borderColor: "#cc3333",
  },
  deleteButtonText: {
    fontSize: 14,
    fontWeight: "600",
    color: "#cc3333",
  },
  // --- Create category form ---
  formGroup: {
    marginTop: 20,
  },
  label: {
    fontSize: 14,
    fontWeight: "600",
    marginBottom: 6,
  },
  helperText: {
    fontSize: 13,
    marginTop: 8,
  },
  input: {
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 12,
    height: 48,
    fontSize: 16,
  },
  // Applied in addition to `input` for the optional Color/Icon fields so
  // they read as visually distinct from the required Name input (dashed vs
  // solid border) without relying on color -- matches goals.styles.ts /
  // budgets.styles.ts's inputOptional.
  inputOptional: {
    borderStyle: "dashed",
  },
});
