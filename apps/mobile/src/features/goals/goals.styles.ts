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
  noticeText: {
    fontSize: 14,
    marginTop: 12,
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
  amount: {
    fontSize: 24,
    fontWeight: "700",
    marginTop: 12,
  },
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
  // --- Create goal form ---
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
  // Applied in addition to `input` for the optional Target date field so it
  // reads as visually distinct from required text inputs (dashed vs solid
  // border) without relying on color.
  inputOptional: {
    borderStyle: "dashed",
  },
  // Read-only value display (Currency), styled like an input but dimmed to
  // signal it is not editable in this flow.
  readOnlyField: {
    justifyContent: "center",
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 12,
    height: 48,
    opacity: 0.6,
  },
  readOnlyFieldText: {
    fontSize: 16,
  },
});
