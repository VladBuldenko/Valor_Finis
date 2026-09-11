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
  // Compact per-card "Edit goal" control on the Goals list -- smaller than
  // the full-width `button` so it reads as a secondary card action rather
  // than a primary screen action (mirrors Budgets' editButton).
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
  // Compact per-card "Delete goal" control, sized like `editButton` but
  // tinted to read as destructive -- this file otherwise avoids relying on
  // color for emphasis, but a delete action is the one case where a
  // recognizable destructive color is warranted alongside the Alert
  // confirmation's own native destructive styling.
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
  // Compact "tap to open a picker" control used for Status on the Edit Goal
  // form, replacing a permanently-rendered vertical list of options
  // (mirrors Budgets' selectControl, used there for Category and Period).
  selectControl: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 12,
    height: 48,
  },
  selectControlText: {
    fontSize: 16,
  },
  selectControlChevron: {
    fontSize: 14,
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
  // Bottom-sheet picker (React Native's built-in Modal) used for Status
  // selection on the Edit Goal form.
  modalOverlay: {
    flex: 1,
    justifyContent: "flex-end",
    backgroundColor: "rgba(0, 0, 0, 0.4)",
  },
  modalSheet: {
    backgroundColor: "#ffffff",
    borderTopLeftRadius: 16,
    borderTopRightRadius: 16,
    paddingTop: 12,
    paddingBottom: 32,
    paddingHorizontal: 20,
    maxHeight: "70%",
  },
  modalOptionList: {
    marginTop: 4,
  },
  modalTitle: {
    fontSize: 18,
    fontWeight: "700",
    marginBottom: 8,
  },
  modalOption: {
    paddingVertical: 14,
    borderBottomWidth: 1,
  },
  modalOptionText: {
    fontSize: 16,
  },
  modalOptionSelectedText: {
    fontWeight: "700",
  },
  modalCloseButton: {
    alignItems: "center",
    borderWidth: 1,
    borderRadius: 10,
    paddingVertical: 14,
    marginTop: 16,
  },
});
