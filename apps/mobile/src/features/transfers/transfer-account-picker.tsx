import { useState } from "react";
import { Modal, Pressable, ScrollView, Text } from "react-native";

import type { Account } from "../accounts/account.types";
import { styles } from "./transfers.styles";

type TransferAccountPickerProps = {
  // The Accounts this picker may offer, already filtered by the caller
  // (active only; for the destination also excluding the source and
  // limited to the source's currency).
  options: Account[];
  // The selected Account id; it only displays as selected while it is one
  // of `options`.
  selectedAccountId: string | null;
  onChange: (accountId: string) => void;
  title: string;
  placeholder: string;
  disabled?: boolean;
};

/**
 * Required Account selector for a transfer's source or destination
 * (bottom-sheet Modal, like ../accounts/account-picker.tsx).
 *
 * Unlike the Income/Expense AccountPicker it has no "No account" option
 * (both sides of a transfer are mandatory) and no "keep the current
 * archived link" exception (a new transfer can never involve an archived
 * Account). A selected id that is not among `options` shows the
 * placeholder, so what is displayed is always what can be submitted. It
 * never computes balances; the backend is the authority on which Accounts
 * are valid.
 */
export function TransferAccountPicker({
  options,
  selectedAccountId,
  onChange,
  title,
  placeholder,
  disabled = false,
}: TransferAccountPickerProps) {
  const [isVisible, setIsVisible] = useState(false);

  const selectedAccount = options.find(
    (account) => account.id === selectedAccountId,
  );

  function handleSelect(accountId: string) {
    onChange(accountId);
    setIsVisible(false);
  }

  return (
    <>
      <Pressable
        accessibilityRole="button"
        accessibilityState={{ disabled }}
        disabled={disabled}
        style={[styles.selectControl, disabled && styles.selectControlDisabled]}
        onPress={() => setIsVisible(true)}
      >
        <Text style={styles.selectControlText}>
          {selectedAccount
            ? `${selectedAccount.name} — ${selectedAccount.currency}`
            : placeholder}
        </Text>

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
            <Text style={styles.modalTitle}>{title}</Text>

            <ScrollView style={styles.modalOptionList}>
              {options.map((account) => {
                const isSelected = account.id === selectedAccountId;
                const label = `${account.name} — ${account.currency}`;

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
