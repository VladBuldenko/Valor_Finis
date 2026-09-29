import { StyleSheet } from "react-native";

// Transfers list/create styles. Mirrors ../accounts/accounts.styles.ts
// (layout, cards, form controls, bottom-sheet picker) so Transfers read as
// part of the same app.
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
  // --- Transfer card: status and badges ---
  statusRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    alignItems: "center",
    marginTop: 8,
  },
  statusText: {
    fontSize: 15,
    fontWeight: "600",
    marginRight: 8,
  },
  // Text badges ("Due", "Blocked") -- bordered labels that stay readable
  // without relying on color.
  badge: {
    borderWidth: 1,
    borderRadius: 6,
    paddingVertical: 2,
    paddingHorizontal: 8,
    marginRight: 8,
  },
  badgeText: {
    fontSize: 12,
    fontWeight: "700",
  },
  // --- Transfer card: actions ---
  actionRow: {
    flexDirection: "row",
    flexWrap: "wrap",
  },
  actionButton: {
    alignItems: "center",
    borderWidth: 1,
    borderRadius: 8,
    paddingVertical: 8,
    paddingHorizontal: 14,
    marginTop: 12,
    marginRight: 8,
  },
  actionButtonText: {
    fontSize: 14,
    fontWeight: "600",
  },
  // Destructive "Delete transfer" control -- tinted like Accounts' and
  // Goals' deleteButton, alongside the Alert confirmation's own native
  // destructive styling.
  deleteButton: {
    alignItems: "center",
    borderWidth: 1,
    borderRadius: 8,
    paddingVertical: 8,
    paddingHorizontal: 14,
    marginTop: 12,
    borderColor: "#cc3333",
  },
  deleteButtonText: {
    fontSize: 14,
    fontWeight: "600",
    color: "#cc3333",
  },
  // --- Create Transfer form ---
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
  inputOptional: {
    borderStyle: "dashed",
  },
  selectControl: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 12,
    height: 48,
  },
  selectControlDisabled: {
    borderStyle: "dashed",
  },
  selectControlText: {
    fontSize: 16,
  },
  selectControlChevron: {
    fontSize: 14,
  },
  // --- Bottom-sheet Account picker (mirrors accounts.styles modal*) ---
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
