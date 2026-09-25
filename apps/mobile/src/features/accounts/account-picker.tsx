import { useState } from "react";
import { Modal, Pressable, ScrollView, Text } from "react-native";

import { styles } from "./accounts.styles";
import type { Account } from "./account.types";

type AccountPickerProps = {
  // The full ["accounts", userId] list (active and archived), exactly as
  // the backend returned it.
  accounts: Account[];
  // The currently selected Account id, or null for "No account".
  selectedAccountId: string | null;
  onChange: (accountId: string | null) => void;
  // The Account the record is persisted as linked to (edit flows only).
  // Kept selectable even when archived, so an existing link can stay
  // unchanged -- the backend permits keeping/correcting a link to an
  // Account that was archived afterward, it only rejects NEW activity
  // against an archived Account.
  currentLinkedAccountId?: string | null;
};

// Presentation-only display label: name, currency, and an archived marker.
// Currency is always shown because a linked record's currency must match
// its Account's currency -- the backend enforces that rule; this label
// only makes it visible before the user submits.
function getAccountOptionLabel(account: Account): string {
  const label = `${account.name} — ${account.currency}`;

  return account.status === "archived" ? `${label} (archived)` : label;
}

/**
 * Reusable "tap to open" Account selector (bottom-sheet Modal, matching
 * the Type/Category pickers used elsewhere in this app).
 *
 * Offers "No account" plus ACTIVE Accounts as destinations; the only
 * archived Account ever offered is currentLinkedAccountId, so an existing
 * link can be left as-is. It never filters by currency, never changes
 * other form fields, and never computes balances -- the backend remains
 * the sole authority on which link is valid (ownership, archived status,
 * exact currency match).
 *
 * The Modal content does not consume safe-area insets (no SafeAreaView or
 * useSafeAreaInsets inside the sheet), so no extra SafeAreaProvider is
 * mounted inside it.
 */
export function AccountPicker({
  accounts,
  selectedAccountId,
  onChange,
  currentLinkedAccountId = null,
}: AccountPickerProps) {
  const [isVisible, setIsVisible] = useState(false);

  const options = accounts.filter(
    (account) =>
      account.status === "active" || account.id === currentLinkedAccountId,
  );

  const selectedAccount =
    selectedAccountId === null
      ? undefined
      : accounts.find((account) => account.id === selectedAccountId);

  // A selected id that cannot be resolved (e.g. a stale cache) gets a
  // neutral label rather than a raw UUID.
  const selectedLabel =
    selectedAccountId === null
      ? "No account"
      : selectedAccount
        ? getAccountOptionLabel(selectedAccount)
        : "Linked account unavailable";

  function handleSelect(accountId: string | null) {
    onChange(accountId);
    setIsVisible(false);
  }

  return (
    <>
      <Pressable
        accessibilityRole="button"
        style={styles.selectControl}
        onPress={() => setIsVisible(true)}
      >
        <Text style={styles.selectControlText}>{selectedLabel}</Text>

        <Text style={styles.selectControlChevron}>▾</Text>
      </Pressable>

      <Modal
        visible={isVisible}
        transparent
        animationType="slide"
        onRequestClose={() => setIsVisible(false)}
      >
        <Pressable
          style={styles.modalOverlay}
          onPress={() => setIsVisible(false)}
        >
          <Pressable
            style={styles.modalSheet}
            onPress={(event) => event.stopPropagation()}
          >
            <Text style={styles.modalTitle}>Select account</Text>

            <ScrollView style={styles.modalOptionList}>
              <Pressable
                style={styles.modalOption}
                onPress={() => handleSelect(null)}
              >
                <Text
                  style={[
                    styles.modalOptionText,
                    selectedAccountId === null &&
                      styles.modalOptionSelectedText,
                  ]}
                >
                  {selectedAccountId === null ? "✓ No account" : "No account"}
                </Text>
              </Pressable>

              {options.map((account) => {
                const isSelected = account.id === selectedAccountId;
                const label = getAccountOptionLabel(account);

                return (
                  <Pressable
                    key={account.id}
                    style={styles.modalOption}
                    onPress={() => handleSelect(account.id)}
                  >
                    <Text
                      style={[
                        styles.modalOptionText,
                        isSelected && styles.modalOptionSelectedText,
                      ]}
                    >
                      {isSelected ? `✓ ${label}` : label}
                    </Text>
                  </Pressable>
                );
              })}
            </ScrollView>

            <Pressable
              style={styles.modalCloseButton}
              onPress={() => setIsVisible(false)}
            >
              <Text style={styles.buttonText}>Close</Text>
            </Pressable>
          </Pressable>
        </Pressable>
      </Modal>
    </>
  );
}
