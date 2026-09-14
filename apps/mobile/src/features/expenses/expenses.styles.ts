import { StyleSheet } from "react-native";

// Feature-local styles for the Expenses screen (create form + list), mirroring
// the proven Budget Create conventions (see budgets/budgets.styles.ts and the
// VF-007D device-review fix) rather than introducing a new visual pattern.
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
  // "Create expense" heading, directly under the screen title.
  sectionTitle: {
    fontSize: 20,
    fontWeight: "700",
    marginTop: 32,
  },
  // "Recent expenses" heading -- the top border visually separates the list
  // section from the create form above it, per the task's requirement to
  // keep the two areas visually distinct on one scrollable screen.
  listSectionTitle: {
    fontSize: 20,
    fontWeight: "700",
    marginTop: 32,
    paddingTop: 24,
    borderTopWidth: 1,
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
  // --- Create expense form ---
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
  // Applied in addition to `input` for the optional Description field so it
  // reads as visually distinct from required text inputs (dashed vs solid
  // border) without relying on color.
  inputOptional: {
    borderStyle: "dashed",
  },
  // Compact "tap to open a picker" control used for Category, replacing a
  // permanently-rendered vertical list of category buttons.
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
  // Bottom-sheet picker (React Native's built-in Modal) used for Category
  // selection.
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
