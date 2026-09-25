import { useState } from "react";
import { Modal, Pressable, Text, View } from "react-native";

import { styles } from "./income.styles";
import {
  INCOME_SOURCE_LABELS,
  INCOME_SOURCES,
  type IncomeSource,
} from "./income.types";

type IncomeSourcePickerProps = {
  value: IncomeSource;
  onChange: (source: IncomeSource) => void;
};

/**
 * "Tap to open" Source selector shared by Create and Edit Income
 * (bottom-sheet Modal, matching the Type picker on Create/Edit Account).
 */
export function IncomeSourcePicker({ value, onChange }: IncomeSourcePickerProps) {
  const [isVisible, setIsVisible] = useState(false);

  return (
    <>
      <Pressable
        accessibilityRole="button"
        style={styles.selectControl}
        onPress={() => setIsVisible(true)}
      >
        <Text style={styles.selectControlText}>
          {INCOME_SOURCE_LABELS[value]}
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
            <Text style={styles.modalTitle}>Select source</Text>

            <View style={styles.modalOptionList}>
              {INCOME_SOURCES.map((option) => (
                <Pressable
                  key={option}
                  style={styles.modalOption}
                  onPress={() => {
                    onChange(option);
                    setIsVisible(false);
                  }}
                >
                  <Text
                    style={[
                      styles.modalOptionText,
                      value === option && styles.modalOptionSelectedText,
                    ]}
                  >
                    {value === option
                      ? `✓ ${INCOME_SOURCE_LABELS[option]}`
                      : INCOME_SOURCE_LABELS[option]}
                  </Text>
                </Pressable>
              ))}
            </View>

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
