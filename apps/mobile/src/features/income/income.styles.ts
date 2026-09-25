import { StyleSheet } from "react-native";

// Mirrors ../accounts/accounts.styles.ts so Income reads as part of the
// same app, limited to what the Income list/create/edit screens use.
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
  // Compact per-card "Edit income" control -- a secondary card action,
  // smaller than the full-width `button`.
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
  // Destructive-tinted "Delete income" control, paired with a native
  // destructive Alert confirmation. Mirrors Accounts' deleteButton.
  deleteButton: {
    alignItems: "center",
    borderWidth: 1,
    borderRadius: 10,
    paddingVertical: 14,
    marginTop: 16,
    borderColor: "#cc3333",
  },
  deleteButtonText: {
    fontSize: 16,
    fontWeight: "600",
    color: "#cc3333",
  },
  // --- Create / Edit Income form ---
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
  // Dashed border marks optional fields without relying on color.
  inputOptional: {
    borderStyle: "dashed",
  },
  // "Tap to open a picker" control for Source.
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
  // Bottom-sheet Source picker (React Native's built-in Modal).
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
