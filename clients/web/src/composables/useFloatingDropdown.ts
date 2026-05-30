import { type CSSProperties, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";

export interface FloatingDropdownOptions {
    canOpen?: () => boolean;
    gap?: number;
    margin?: number;
    minHeight?: number;
}

export function useFloatingDropdown(options: FloatingDropdownOptions = {}) {
    const isOpen = ref(false);
    const triggerRef = ref<HTMLElement | null>(null);
    const menuRef = ref<HTMLElement | null>(null);
    const menuStyle = ref<CSSProperties>({});

    const canOpen = () => options.canOpen?.() ?? true;

    watch(isOpen, async (open) => {
        if (!open) return;

        await nextTick();
        updateMenuPosition();
    });

    function open(): void {
        if (!canOpen()) return;
        isOpen.value = true;
    }

    function toggle(): void {
        if (!canOpen()) return;
        isOpen.value = !isOpen.value;
    }

    function close(): void {
        isOpen.value = false;
    }

    function onDocumentPointerDown(event: PointerEvent): void {
        const target = event.target as Node | null;
        if (!target) return;

        if (triggerRef.value?.contains(target) || menuRef.value?.contains(target)) {
            return;
        }

        close();
    }

    function updateMenuPosition(): void {
        if (!triggerRef.value || !menuRef.value) return;

        const margin = options.margin ?? 12;
        const gap = options.gap ?? 4;
        const minHeight = options.minHeight ?? 120;
        const triggerRect = triggerRef.value.getBoundingClientRect();
        const menuRect = menuRef.value.getBoundingClientRect();
        const viewportWidth = window.innerWidth;
        const viewportHeight = window.innerHeight;
        const menuWidth = Math.min(menuRect.width, viewportWidth - margin * 2);
        const belowSpace = viewportHeight - triggerRect.bottom - gap - margin;
        const aboveSpace = triggerRect.top - gap - margin;
        const opensDown = belowSpace >= menuRect.height || belowSpace >= aboveSpace;
        const maxHeight = Math.max(minHeight, opensDown ? belowSpace : aboveSpace);

        let left = triggerRect.left;
        if (left + menuWidth > viewportWidth - margin) {
            left = triggerRect.right - menuWidth;
        }
        left = Math.max(margin, Math.min(left, viewportWidth - margin - menuWidth));

        const naturalTop = opensDown ? triggerRect.bottom + gap : triggerRect.top - gap - menuRect.height;
        const top = opensDown ? naturalTop : Math.max(margin, naturalTop);

        menuStyle.value = {
            left: `${left}px`,
            top: `${top}px`,
            minWidth: `${triggerRect.width}px`,
            maxWidth: `${viewportWidth - margin * 2}px`,
            maxHeight: `${maxHeight}px`,
        };
    }

    function onTriggerKeydown(event: KeyboardEvent): void {
        if (event.key === "Escape") {
            close();
            return;
        }

        if (event.key === "Enter" || event.key === " " || event.key === "ArrowDown") {
            event.preventDefault();
            if (!isOpen.value) {
                open();
            }
        }
    }

    onMounted(() => {
        document.addEventListener("pointerdown", onDocumentPointerDown);
        window.addEventListener("resize", updateMenuPosition);
        window.addEventListener("scroll", updateMenuPosition, true);
    });

    onBeforeUnmount(() => {
        document.removeEventListener("pointerdown", onDocumentPointerDown);
        window.removeEventListener("resize", updateMenuPosition);
        window.removeEventListener("scroll", updateMenuPosition, true);
    });

    return {
        isOpen,
        triggerRef,
        menuRef,
        menuStyle,
        open,
        toggle,
        close,
        updateMenuPosition,
        onTriggerKeydown,
    };
}
