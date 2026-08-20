import {
    SafeAreaView,
    StyleSheet,
    Text,
    View,
  } from "react-native";
  
  export default function DashboardScreen() {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.content}>
          <Text style={styles.title}>
            Valor Finis
          </Text>
  
          <Text style={styles.subtitle}>
            Dashboard
          </Text>
        </View>
      </SafeAreaView>
    );
  }
  
  const styles = StyleSheet.create({
    container: {
      flex: 1,
    },
    content: {
      flex: 1,
      paddingHorizontal: 24,
      paddingTop: 32,
    },
    title: {
      fontSize: 32,
      fontWeight: "700",
    },
    subtitle: {
      fontSize: 20,
      marginTop: 8,
    },
  });