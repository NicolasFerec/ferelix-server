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
let pendingUser: Promise<User | null> | null = null;
let userGeneration = 0;

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

        if (pendingUser) return pendingUser;
        const generation = userGeneration;
        isLoading.value = true;
        const pending = auth
            .getCurrentUser()
            .then((userData) => {
                if (generation !== userGeneration || !checkAuth()) return null;
                currentUser.value = userData;
                return userData;
            })
            .catch((error) => {
                console.error("Failed to load user:", error);
                if (generation === userGeneration) currentUser.value = null;
                return null;
            })
            .finally(() => {
                if (pendingUser === pending) {
                    pendingUser = null;
                    isLoading.value = false;
                }
            });
        pendingUser = pending;
        return pending;
    }

    /**
     * Clear user data (on logout)
     */
    function clearUser(): void {
        userGeneration++;
        pendingUser = null;
        isLoading.value = false;
        currentUser.value = null;
    }

    /**
     * Update user data
     */
    function updateUser(userData: Partial<User>): void {
        userGeneration++;
        pendingUser = null;
        isLoading.value = false;
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
