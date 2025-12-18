import { type ComputedRef, computed, type Ref, ref } from "vue";
import { auth, isAuthenticated as checkAuth, type User } from "@/api/client";

interface UseUserReturn {
  // State
  user: ComputedRef<User | null>;
  isAuthenticated: ComputedRef<boolean>;
  isAdmin: ComputedRef<boolean>;
  isLoading: Ref<boolean>;

  // Methods
  loadUser: () => Promise<User | null>;
  clearUser: () => void;
  updateUser: (userData: Partial<User>) => void;
}

// Reactive state for current user
const currentUser: Ref<User | null> = ref(null);
const isLoading: Ref<boolean> = ref(false);

/**
 * Composable for managing user state and authentication
 */
export function useUser(): UseUserReturn {
  // Computed properties for easy access
  const isAuthenticated: ComputedRef<boolean> = computed(() => !!currentUser.value);
  const isAdmin: ComputedRef<boolean> = computed(() => currentUser.value?.is_admin === true);
  const user: ComputedRef<User | null> = computed(() => currentUser.value);

  /**
   * Load current user information
   */
  async function loadUser(): Promise<User | null> {
    if (!checkAuth()) {
      currentUser.value = null;
      return null;
    }

    isLoading.value = true;
    try {
      const userData = await auth.getCurrentUser();
      currentUser.value = userData;
      return userData;
    } catch (error) {
      console.error("Failed to load user:", error);
      currentUser.value = null;
      return null;
    } finally {
      isLoading.value = false;
    }
  }

  /**
   * Clear user data (on logout)
   */
  function clearUser(): void {
    currentUser.value = null;
  }

  /**
   * Update user data
   */
  function updateUser(userData: Partial<User>): void {
    currentUser.value = { ...currentUser.value, ...userData };
  }

  return {
    // State
    user,
    isAuthenticated,
    isAdmin,
    isLoading,

    // Methods
    loadUser,
    clearUser,
    updateUser,
  };
}
