from mods_base import build_mod #type:ignore
from typing import Any #type:ignore
import unrealsdk #type:ignore
from unrealsdk import construct_object, find_object #type:ignore
from mods_base import get_pc, hook, keybind, build_mod, ENGINE, SliderOption, BoolOption #type:ignore
from unrealsdk.hooks import Type, add_hook, Block, remove_hook, inject_next_call, prevent_hooking_direct_calls #type:ignore
from unrealsdk.unreal import BoundFunction, UObject, WrappedStruct #type:ignore
from ui_utils import show_hud_message #type:ignore

sell_audio = None
can_swap = True
cash_amount = 0

@keybind("Backpack Sell Key")
def sell_key():
    return

@hook("WillowGame.WillowPlayerController:SawPickupable", Type.PRE)
def add_interact_icon(obj: UObject, __args: WrappedStruct, __ret: Any, __func: BoundFunction) -> bool:
    global cash_amount, can_swap
    if is_client(): # Removes functionality when the user is not the host
        return True

    base_icon = find_object("InteractionIconDefinition", "GD_InteractionIcons.Default.Icon_DefaultUse")
    icon = construct_object(
                cls=base_icon.Class,
                outer=base_icon.Outer,
                name="SecondaryUse",
                flags=0,
                template_obj=base_icon,
            )
    icon.ObjectFlags |= 0x4000
    icon.Icon = 4 # Dollar sign icon
    obj.ServerRCon(f"set {obj.PathName(icon)} Action UseSecondary")
    obj.ServerRCon(f"set {obj.PathName(icon)} Text SELL ITEM")
    
    InteractionIconWithOverrides = unrealsdk.make_struct(
        "InteractionIconWithOverrides",
        IconDef=icon,
        OverrideIconDef=None,
        bOverrideIcon=False,
        bOverrideAction=False,
        bOverrideText=False,
        bCostsToUse=0,
        CostsCurrencyType=0,
        CostsAmount=0
    )
    
    seen_item_type = __args.Pickup.Inventory.Class.Name
    cash_amount = __args.Pickup.Inventory.MonetaryValue

    if seen_item_type != "WillowUsableItem" and seen_item_type != "WillowMissionItem": # Checks the type of item the player is looking at to make sure its something sellable
        hud_movie = obj.GetHUDMovie()
        if hud_movie == None: # This fixes an error that is caused when looking at a pickupable directly after closing the inventory
            return True
        hud_movie.ShowToolTip(InteractionIconWithOverrides, 1) # Show the tooltip in the hud
        if obj.PlayerInput.bUsingGamepad is True:
            can_swap = False # Because the Secondary Use Key on controller is the same as swap weapons, we need to restrict the ability to swap when looking at a pickupable object
    return True

@hook("WillowGame.WillowPlayerController:PerformedSecondaryUseAction", Type.PRE)
def on_use(obj: UObject, __args: WrappedStruct, __ret: Any, __func: BoundFunction) -> bool:
    global cash_amount
    inv_manager = get_pc().GetPawnInventoryManager()

    if is_client(): # Disables selling off the floor if you are not the host
        return True
    
    seen_item = obj.CurrentSeenPickupable
    if seen_item == None: # If the player is looking at nothing, we do nothing
        return True
    seen_item_type = seen_item.Inventory.Class.Name
    
    if seen_item_type != "WillowUsableItem" and seen_item_type != "WillowMissionItem": # Checks the type of item the player is looking at to make sure its something sellable
        if seen_item.bPickupable == True and seen_item.bIsMissionItem == False:
            seen_item.SetPickupability(False) # Turn off the ability for the player to pick up the item
            seen_item.PickupShrinkDuration = 0.5
            seen_item.BeginShrinking() # Deletes the gun 
            obj.PlayerSoldItem(0, cash_amount) # Adds the monetary value of the item to the players current cash amount
            inv_manager.ClientConditionalIncrementPickupStats(seen_item.Inventory) # Increases Badass Rank pickup stats (Only if the item has not be picked up)
            update_buy_back(inv_manager, seen_item.Inventory) # Updates the buyback inventory
            play_sound() # Plays the vendor sell sound
    return True

@hook("WillowGame.StatusMenuInventoryPanelGFxObject:SetTooltipText", Type.POST)
def set_tooltip_text(obj: UObject, __args: WrappedStruct, __ret: Any, __func: BoundFunction) -> bool:
    if sell_key.key == None:
        sell_key.key = get_pc().PlayerInput.GetKeyForAction("UseSecondary")

    if obj.bInEquippedView is True: # Only show updated tooltip when looking at the backpack as you cannot delete items that are equipped
        return True

    if get_pc().PlayerInput.bUsingGamepad is False:
        result = f"{__args.TooltipsText}\n[{sell_key.key}] Sell Item" # Connects the normal tooltip text with our custom text
    if get_pc().PlayerInput.bUsingGamepad is True:
        result = f"{__args.TooltipsText}\n<IMG src='xbox360_Start' vspace='-3'> Sell Item" # Connects the normal tooltip text with our custom text

    with prevent_hooking_direct_calls():
        __func(result)
    return False

@hook("WillowGame.StatusMenuInventoryPanelGFxObject:NormalInputKey", Type.PRE)
def on_use_backpack(obj: UObject, __args: WrappedStruct, __ret: Any, __func: BoundFunction) -> bool:
    inv_manager = get_pc().GetPawnInventoryManager()

    if get_pc().PlayerInput.bUsingGamepad is False:
        if __args.ukey != sell_key.key: # Looks for Secondary Use Key
            return True
    if get_pc().PlayerInput.bUsingGamepad is True:
        if "Start" not in str(__args.ukey): # Looks for Start button
            return True
        
    if __args.Uevent == 0: # Checks if pressed
        selected_item = obj.GetSelectedThing() # Gets Willow Definition of selected item in inventory
        if selected_item is None or obj.bInEquippedView is True or selected_item.GetMark() == 2:
            obj.ParentMovie.PlayUISound('ResultFailure') # Plays an error sound if player tries to sell an item that is either equipped or favorited
            return True
        
        obj.BackpackPanel.SaveState() # Saves the current index of the item you are hovering
        get_pc().PlayerSoldItem(0, selected_item.GetMonetaryValue()) # Adds the monetary value of the item to the players current cash amount
        inv_manager.RemoveInventoryFromBackpack(selected_item) # Deletes the item from your backpack
        obj.FlourishEquip("SOLD") # Displays a confirmation message
        update_buy_back(inv_manager, selected_item) # Updates the buyback inventory
        play_sound() # Plays the vendor sell sound

        inv_manager.UpdateBackpackInventoryCount() # Fixes an issue where the player could not pickup guns if they sold an item while their backpack was full
        obj.ParentMovie.RefreshInventoryScreen(True)
        obj.BackpackPanel.RestoreState() # Sets the current selected item to the one of the same index that was saved previously
    return True

@hook("WillowGame.WillowPlayerController:ClearSeenPickupable", Type.PRE)
def noPickup(obj: UObject, __args: WrappedStruct, __ret: Any, __func: BoundFunction) -> bool:
    global can_swap
    can_swap = True # Allows the player to swap weapons after looking away from a pickupable
    return True

@hook("WillowGame.WillowPlayerController:NextWeapon", Type.PRE)
def onSwap(obj: UObject, __args: WrappedStruct, __ret: Any, __func: BoundFunction) -> bool:
    global can_swap
    return can_swap # Controls the players ability to swap weapons

def play_sound() -> None:
    global sell_audio
    # Took the sell audio search from apple1417's "AltUseVendors" (https://bl-sdk.github.io/mods/AltUseVendors/)
    if sell_audio is None:
        sell_audio = find_object("AkEvent", 'Ake_UI.UI_Vending.Ak_Play_UI_Vending_Sell')
        sell_audio.ObjectFlags |= 0x4000 # Keep Alive
    get_pc().Pawn.PlayAkEvent(sell_audio)
    return

# def getsell_key() -> str:
#     if useCustomKey.value is True: # Checks if the user is using a custom sell bind
#         return sell_key.key # Returns the custom bind
#     else:
#         return get_pc().PlayerInput.GetKeyForAction("UseSecondary") # Returns the secondary use bind

def update_buy_back(invManager, item) -> str:
    buy_back = [entry for entry in invManager.BuyBackInventory] # Creates a list of the items currently in your buyback inventory
    buy_back.append(item.CreateClone()) # Creates a clone of the item you just sold and adds it to the buyback list
    if len(buy_back) > 20:
        buy_back.pop(0) # Removes first item in the list once it reaches a length of 20 (default max)
    invManager.BuyBackInventory = buy_back # Replaces the current buyback inventory with the one we created
    return

def is_client() -> bool:
    # List of all roles and their enums
    # 0 - None
    # 1 - SimulatedProxy
    # 2 - AutonomousProxy
    # 3 - Authority
    # 4 - MAX
    return get_pc().Role < 3 # Checks if you are not the host

build_mod()