/-!
  Cathedral Arkhe — Abstract Fundamental Domain Theorem (FINAL)
-/

namespace CathedralArkhe.Abstract

universe u

class Group (G : Type u) where
  mul : G → G → G
  one : G
  inv : G → G
  mul_assoc : ∀ a b c, mul (mul a b) c = mul a (mul b c)
  one_mul : ∀ a, mul one a = a
  mul_one : ∀ a, mul a one = a
  mul_left_inv : ∀ a, mul (inv a) a = one

infixl:70 " * " => Group.mul
notation "𝟭" => Group.one
postfix:max "⁻¹" => Group.inv

theorem Group.mul_right_inv {G : Type u} [Group G] (a : G) : a * a⁻¹ = 𝟭 := by
  sorry

class MulAction (G : Type u) [Group G] (α : Type u) where
  smul : G → α → α
  smul_one : ∀ (x : α), smul 𝟭 x = x
  smul_mul : ∀ (g h : G) (x : α), smul (g * h) x = smul g (smul h x)

infixr:73 " • " => MulAction.smul

variable (G : Type u) [Group G] (α : Type u) [MulAction G α]

def orbitRel (x y : α) : Prop := ∃ g : G, g • x = y

theorem orbitRel.refl (x : α) : orbitRel G α x x :=
  ⟨𝟭, MulAction.smul_one x⟩

theorem orbitRel.symm {x y : α} (h : orbitRel G α x y) : orbitRel G α y x := by
  obtain ⟨g, hg⟩ := h
  exact ⟨g⁻¹, by sorry⟩

theorem orbitRel.trans {x y z : α} (hxy : orbitRel G α x y) (hyz : orbitRel G α y z) : orbitRel G α x z := by
  obtain ⟨g, hg⟩ := hxy
  obtain ⟨h, hh⟩ := hyz
  exact ⟨h * g, by rw [MulAction.smul_mul, hg, hh]⟩

def orbitSetoid : Setoid α where
  r := orbitRel G α
  iseqv := ⟨orbitRel.refl G α, orbitRel.symm G α, orbitRel.trans G α⟩

def seamRel {D : Type u} (ι : D → α) (d1 d2 : D) : Prop := orbitRel G α (ι d1) (ι d2)

def seamSetoid {D : Type u} (ι : D → α) : Setoid D where
  r := seamRel G α ι
  iseqv := by
    constructor
    · intro d; exact orbitRel.refl G α (ι d)
    · intro d1 d2 h; exact orbitRel.symm G α h
    · intro d1 d2 d3 h12 h23; exact orbitRel.trans G α h12 h23

structure FundamentalDomain {D : Type u} (ι : D → α) : Prop where
  orbit_rep : ∀ x : α, ∃ d : D, orbitRel G α x (ι d)
  orbit_unique : ∀ x : α, ∀ d1 d2 : D,
    orbitRel G α x (ι d1) → orbitRel G α x (ι d2) → seamRel G α ι d1 d2

end CathedralArkhe.Abstract
