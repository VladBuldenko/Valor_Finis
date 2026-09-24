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
  // Compact per-card "Open account" / "Edit account" control on the
  // Accounts list -- smaller than the full-width `button` so it reads as a
  // secondary card action rather than a primary screen action (mirrors
  // Goals' editButton).
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
  // Compact per-card/detail "Delete account" control, sized like
  // `editButton` but tinted to read as destructive -- this file otherwise
  // avoids relying on color for emphasis, but a delete action is the one
  // case where a recognizable destructive color is warranted alongside the
  // Alert confirmation's own native destructive styling. Mirrors Goals'
  // deleteButton exactly.
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
  // --- Create / Edit Account form ---
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
  // Applied in addition to `input` for optional fields (opening_balance,
  // opening_balance_date) so they read as visually distinct from required
  // text inputs (dashed vs solid border) without relying on color --
  // mirrors Goals' inputOptional exactly.
  inputOptional: {
    borderStyle: "dashed",
  },
  // Compact "tap to open a picker" control used for the Type field
  // (checking/savings/cash) on Create and Edit Account -- mirrors Goals'
  // selectControl, used there for Status.
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
  // Bottom-sheet picker (React Native's built-in Modal) used for Type
  // selection on Create/Edit Account -- mirrors Goals' modal* set exactly.
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
  // --- Accounts list active/archived toggle, Account detail direction toggle ---
  sectionTitle: {
    fontSize: 20,
    fontWeight: "700",
    marginTop: 28,
  },
  typeToggleRow: {
    flexDirection: "row",
    marginTop: 16,
  },
  typeToggleButton: {
    flex: 1,
    alignItems: "center",
    borderWidth: 1,
    borderRadius: 8,
    paddingVertical: 12,
    marginRight: 8,
  },
  typeToggleButtonSelected: {
    borderWidth: 2,
  },
  typeToggleButtonText: {
    fontSize: 15,
    fontWeight: "600",
  },
  typeToggleButtonTextSelected: {
    fontWeight: "700",
  },
  // --- Account detail: lifecycle actions ---
  archiveButton: {
    alignItems: "center",
    borderWidth: 1,
    borderRadius: 10,
    paddingVertical: 14,
    marginTop: 16,
  },
  archiveButtonText: {
    fontSize: 16,
    fontWeight: "600",
  },
  // --- Account detail: transaction history ---
  historyList: {
    marginTop: 12,
  },
  historyRow: {
    paddingVertical: 12,
    borderBottomWidth: 1,
  },
  historyRowHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  historyType: {
    fontSize: 15,
    fontWeight: "600",
  },
  historyAmount: {
    fontSize: 15,
    fontWeight: "600",
  },
  historyDescription: {
    fontSize: 14,
    marginTop: 4,
  },
  historyDate: {
    fontSize: 12,
    marginTop: 4,
  },
});
