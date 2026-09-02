import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva("inline-flex items-center justify-center gap-2 rounded-control border px-3 py-2 text-xs font-medium transition duration-120 disabled:cursor-not-allowed disabled:opacity-45", {
  variants: { variant: { primary: "border-cyan/40 bg-cyan/10 text-cyan hover:bg-cyan/15 active:bg-cyan/20", neutral: "border-strong bg-raised text-secondary hover:bg-surface-hover hover:text-foreground", ghost: "border-transparent bg-transparent text-secondary hover:bg-surface-hover hover:text-foreground", danger: "border-negative/40 bg-negative/10 text-negative hover:bg-negative/15" } },
  defaultVariants: { variant: "neutral" },
});

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {}
export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(({ className, variant, type = "button", ...props }, ref) => <button ref={ref} type={type} className={cn(buttonVariants({ variant }), className)} {...props} />);
Button.displayName = "Button";
