export default defineAppConfig({
  ui: {
    card: {
      slots: {
        root: "rounded-2xl bg-elevated/80 ring ring-default shadow-sm",
        header: "p-5",
        body: "p-5",
        footer: "p-5",
        title: "text-base font-semibold tracking-tight text-highlighted",
        description: "mt-1.5 text-sm leading-6 text-muted",
      },
    },
    modal: {
      slots: {
        overlay: "overflow-x-hidden bg-black/75 backdrop-blur-sm",
        content: "rounded-2xl bg-default ring ring-accented shadow-2xl",
        header: "min-h-18 p-5 sm:px-6",
        body: "p-5 sm:p-6",
        footer: "p-5 sm:px-6",
        title: "text-xl font-semibold tracking-tight text-highlighted",
        description: "mt-1.5 text-sm leading-6 text-muted",
      },
    },
    button: {
      slots: {
        base: "rounded-lg",
      },
    },
    input: {
      slots: {
        base: "rounded-lg",
      },
    },
    textarea: {
      slots: {
        base: "rounded-lg",
      },
    },
    select: {
      slots: {
        base: "rounded-lg",
      },
    },
    badge: {
      slots: {
        base: "rounded-full",
      },
    },
  },
});
